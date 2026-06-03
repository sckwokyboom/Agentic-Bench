# abench/opencode_client.py
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Protocol

from .config import OpenCodeCfg
from .trace_model import Trace
from .trace_normalize import normalize

_PRINT_LOCK = threading.Lock()


def _log(msg: str) -> None:
    """Write a single line to stderr under a lock so concurrent threads
    (stdout reader, stderr drainer, runner) don't interleave mid-line."""
    with _PRINT_LOCK:
        sys.stderr.write(msg + "\n")
        sys.stderr.flush()


def _truncate(text: str, n: int) -> str:
    text = text.replace("\n", " ").strip()
    return text if len(text) <= n else text[: n - 1] + "…"


def _summarize_event(event: dict) -> str | None:
    """Return a one-line human summary of an OpenCode JSONL event, or None
    if the event is not worth printing live."""
    part = event.get("part") or {}
    ptype = part.get("type")

    if ptype == "text":
        text = part.get("text") or ""
        snippet = _truncate(text, 140)
        return f"  [llm ] {snippet}" if snippet else None

    if ptype == "tool":
        name = part.get("tool") or "?"
        state = part.get("state") or {}
        status = state.get("status")
        args = state.get("input") or {}
        hint = (
            args.get("command")
            or args.get("filePath")
            or args.get("path")
            or args.get("pattern")
            or ""
        )
        hint = _truncate(str(hint), 100)
        tag = {"completed": "ok ", "error": "err"}.get(status, "...")
        return f"  [tool] {tag} {name} {hint}".rstrip()

    if ptype == "reasoning":
        text = part.get("text") or ""
        snippet = _truncate(text, 100)
        return f"  [think] {snippet}" if snippet else "  [think]"

    if event.get("type") == "error" or ptype == "error":
        return f"  [ERR] {_truncate(json.dumps(event), 200)}"

    return None


def _error_payload(ev: dict) -> dict | None:
    """Return the error payload of an event if it is a service/proxy error,
    else None. Recognises both top-level (``type == "error"``) and part-level
    (``part.type == "error"``) error events."""
    if ev.get("type") == "error":
        payload = ev.get("error") or ev.get("part") or {}
        return payload if isinstance(payload, dict) else {}
    part = ev.get("part")
    if isinstance(part, dict) and part.get("type") == "error":
        payload = part.get("error") or part
        return payload if isinstance(payload, dict) else {}
    return None


def _status_of(payload: dict) -> object | None:
    """Extract the HTTP-ish status from an error payload. First key that is
    *present* (not first truthy) wins, so a literal 0 beats a missing field."""
    for key in ("statusCode", "status", "code"):
        if payload.get(key) is not None:
            return payload.get(key)
    return None


def _is_rate_limit(status: object | None) -> bool:
    return status == 429 or str(status) == "429"


def _count_service_errors(raw_events: list[dict]) -> tuple[int, int, list[str]]:
    """Count service/proxy errors across opencode events.

    Returns ``(n_service_errors, n_rate_limits, messages)`` where ``messages``
    holds up to 5 short (~160 char) summaries of the offending events.
    """
    n_service_errors = 0
    n_rate_limits = 0
    messages: list[str] = []
    for ev in raw_events:
        payload = _error_payload(ev)
        if payload is None:
            continue
        n_service_errors += 1
        if _is_rate_limit(_status_of(payload)):
            n_rate_limits += 1
        if len(messages) < 5:
            blob = ev.get("error") or ev.get("part") or ev
            messages.append(_truncate(json.dumps(blob, default=str), 160))
    return n_service_errors, n_rate_limits, messages


@dataclass
class RunResult:
    trace: Trace
    raw_session: dict | None = None


class OpenCodeClient(Protocol):
    def run_task(
        self,
        *,
        workdir: str,
        system_prompt: str,
        model: str,
        user_message: str,
        timeout_s: int,
        on_event: Callable[[dict], None],
        log_sink: Callable[[str], None] | None = None,
    ) -> RunResult:
        ...


class RealOpenCodeClient:
    """Drive ``opencode run`` as a subprocess and produce a normalized :class:`Trace`.

    System-prompt handling — Approach A (workdir-local config):
    ---------------------------------------------------------------------------
    Before each run, a file ``opencode.json`` is written into *workdir*.  It
    defines a custom named agent (``cfg.agent``) whose ``prompt`` key carries
    the caller-supplied *system_prompt*, and pins both ``model`` and
    ``small_model`` (to the free opencode-native model) so the harness is
    self-sufficient regardless of the user's global config.

    Probe evidence (run during Task 13):
        $ mkdir /tmp/oc-probe2
        $ cat > /tmp/oc-probe2/opencode.json << EOF
          {"$schema": "…", "agent": {"abench": {"prompt": "…"}}}
          EOF
        $ cd /tmp/oc-probe2 && opencode debug config --pure
        → agent block shows "abench": {"prompt": "You are a terse test assistant.", …}
    The workdir-local config is merged; the named agent appears.  Approach A works.
    ---------------------------------------------------------------------------
    """

    _SMALL_MODEL_FREE = "opencode/mimo-v2.5-free"

    def __init__(self, cfg: OpenCodeCfg, timeout_s: int = 600) -> None:
        self._cfg = cfg
        # timeout_s stored for callers that construct the client without a
        # per-run override (e.g. tests that call run_task with the same value).
        self.timeout_s = timeout_s

    def run_task(
        self,
        *,
        workdir: str,
        system_prompt: str,
        model: str,
        user_message: str,
        timeout_s: int,
        on_event: Callable[[dict], None],
        log_sink: Callable[[str], None] | None = None,
    ) -> RunResult:
        def emit(line: str) -> None:
            """Send a harness/opencode line to stderr AND, if provided, to the
            per-run log sink (so rundir/run.log captures the full picture).
            A log-write failure (e.g. disk full) must never crash the run."""
            _log(line)
            if log_sink is not None:
                try:
                    log_sink(line)
                except Exception:
                    pass

        # ── Approach A: write workdir-local config ────────────────────────
        workdir_path = Path(workdir)
        config_data = {
            "$schema": "https://opencode.ai/config.json",
            "model": model,
            "small_model": self._SMALL_MODEL_FREE,
            "agent": {
                self._cfg.agent: {
                    "prompt": system_prompt,
                    "model": model,
                }
            },
        }
        (workdir_path / "opencode.json").write_text(
            json.dumps(config_data, indent=2), encoding="utf-8"
        )

        # ── Spawn subprocess ──────────────────────────────────────────────
        started_at = time.time()
        cmd = [
            self._cfg.binary,
            "run",
            "--format", "json",
            "--print-logs",
            "--log-level", "INFO",
            "--dir", workdir,
            "--model", model,
            "--agent", self._cfg.agent,
            "--dangerously-skip-permissions",
            user_message,
        ]

        emit(f"[abench] $ {' '.join(cmd[:6])} … (cwd={workdir})")

        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=workdir,
            env=os.environ.copy(),
        )

        raw_events: list[dict] = []
        interrupted_reason: str | None = None

        def _read_stdout() -> None:
            """Read stdout line by line; parse JSONL; call on_event live and
            print a one-line summary so the operator can see progress."""
            assert proc.stdout is not None
            for line in proc.stdout:
                text = line.decode("utf-8", errors="replace").rstrip()
                if not text:
                    continue
                try:
                    event = json.loads(text)
                except json.JSONDecodeError:
                    continue  # forwards-compat: skip unparseable lines
                raw_events.append(event)
                summary = _summarize_event(event)
                if summary is not None:
                    _log(summary)
                on_event(event)

        def _drain_stderr() -> None:
            """Forward opencode's stderr (``--print-logs INFO`` is verbose,
            but it's the surest signal that the subprocess is alive). Reading
            line-by-line both keeps the OS pipe from filling and lets the user
            see progress in real time."""
            if proc.stderr is None:
                return
            try:
                for raw in proc.stderr:
                    text = raw.decode("utf-8", errors="replace").rstrip()
                    if text:
                        emit(f"  [opencode] {text}")
            except Exception:
                pass

        reader = threading.Thread(target=_read_stdout, daemon=True)
        reader.start()
        stderr_drainer = threading.Thread(target=_drain_stderr, daemon=True)
        stderr_drainer.start()

        # Wait up to timeout_s for the process to finish.
        try:
            proc.wait(timeout=timeout_s)
        except subprocess.TimeoutExpired:
            proc.kill()
            interrupted_reason = "timeout"
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                pass

        reader.join(timeout=10)
        stderr_drainer.join(timeout=10)

        ended_at = time.time()
        returncode = proc.returncode

        # ── Count service/proxy errors (rate limits, 5xx, etc.) ───────────
        n_service_errors, n_rate_limits, service_error_messages = (
            _count_service_errors(raw_events)
        )

        # ── Detect interrupted_reason ─────────────────────────────────────
        if interrupted_reason is None and n_rate_limits > 0:
            interrupted_reason = "rate_limit"

        if interrupted_reason is None and returncode != 0:
            interrupted_reason = "error"

        emit(f"[abench] opencode returncode={returncode} "
             f"interrupted={interrupted_reason} "
             f"service_errors={n_service_errors} rate_limits={n_rate_limits}")

        # ── Session export ────────────────────────────────────────────────
        session_id: str | None = None
        if raw_events:
            session_id = raw_events[0].get("sessionID")

        raw_session: dict | None = None
        if session_id:
            try:
                export_result = subprocess.run(
                    [self._cfg.binary, "export", session_id],
                    capture_output=True,
                    text=True,
                    timeout=30,
                    cwd=workdir,
                )
                raw_output = export_result.stdout
                # Locate the first line that begins the JSON document; this
                # tolerates any number of informational preamble lines that
                # `opencode export` might emit (today: one "Exporting session:
                # <id>" line).
                lines = raw_output.splitlines(keepends=True)
                json_start = next(
                    (i for i, line in enumerate(lines)
                     if line.lstrip().startswith("{")),
                    None,
                )
                if json_start is not None:
                    json_text = "".join(lines[json_start:]).strip()
                    if json_text:
                        raw_session = json.loads(json_text)
            except Exception:
                # Export failure must not poison the trace.
                raw_session = None

        # ── Build and return trace ────────────────────────────────────────
        trace = normalize(raw_events, raw_session)
        trace.started_at = started_at
        trace.ended_at = ended_at
        trace.finished = interrupted_reason is None
        trace.interrupted_reason = interrupted_reason
        trace.n_service_errors = n_service_errors
        trace.n_rate_limits = n_rate_limits
        trace.service_error_messages = service_error_messages

        return RunResult(trace=trace, raw_session=raw_session)
