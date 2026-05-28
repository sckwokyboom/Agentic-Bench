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
    ) -> RunResult:
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

        _log(f"[abench] $ {' '.join(cmd[:6])} … (cwd={workdir})")

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
                        _log(f"  [opencode] {text}")
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

        # ── Detect interrupted_reason ─────────────────────────────────────
        if interrupted_reason is None:
            # Check for rate-limit error (HTTP 429) in any event.
            for ev in raw_events:
                if ev.get("type") == "error":
                    error_payload = ev.get("error") or ev.get("part", {})
                    status = None
                    if isinstance(error_payload, dict):
                        # First key that is *present*, not first that is truthy:
                        # a literal 0 should win over a missing field, even
                        # though HTTP codes are never 0 in practice.
                        for key in ("statusCode", "status", "code"):
                            if error_payload.get(key) is not None:
                                status = error_payload.get(key)
                                break
                    if status == 429 or str(status) == "429":
                        interrupted_reason = "rate_limit"
                        break

        if interrupted_reason is None and returncode != 0:
            interrupted_reason = "error"

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

        return RunResult(trace=trace, raw_session=raw_session)
