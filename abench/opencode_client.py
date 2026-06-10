# abench/opencode_client.py
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Protocol

from .config import OpenCodeCfg
from .envutil import expand_env_refs
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


def build_opencode_config(
    cfg: OpenCodeCfg,
    model: str,
    system_prompt: str,
) -> dict:
    """Build the workdir-local ``opencode.json`` payload.

    Pure (no I/O) so it can be unit-tested without spawning opencode. Secrets
    are NEVER inlined: a provider's API key is referenced as ``{env:NAME}`` (or
    left to opencode's auth.json) — :class:`~abench.config.ProviderCfg` has no
    field that could carry a raw key.

    ``small_model`` defaults to the run's main ``model`` (so the bench talks to
    the SAME provider that the operator's interactive opencode uses) — NOT to an
    opencode-native model, which would inject a second gateway/domain that a
    corporate proxy may forbid even when the main model works. Override via
    ``OpenCodeCfg.small_model`` to use a cheaper helper.
    """
    small = cfg.small_model or model
    config: dict = {
        "$schema": "https://opencode.ai/config.json",
        "model": model,
        "small_model": small,
        "agent": {cfg.agent: {"prompt": system_prompt, "model": model}},
    }
    if cfg.providers:
        prov: dict = {}
        for p in cfg.providers:
            block: dict = {"npm": p.npm, "models": {m: {} for m in p.models}}
            if p.name:
                block["name"] = p.name
            options: dict = {"baseURL": p.base_url}
            if p.api_key_env:
                options["apiKey"] = "{env:" + p.api_key_env + "}"
            block["options"] = options
            prov[p.id] = block
        config["provider"] = prov
    return config


def _run_deadline(started_at: float, timeout_s: int | None) -> float | None:
    """Absolute wall-clock deadline for a run, or None for no limit.

    ``timeout_s`` of None (or <= 0) means the agent may run as long as it needs
    — the run ends on natural completion or a cooperative cancel, never a clock.
    """
    if timeout_s is None or timeout_s <= 0:
        return None
    return started_at + timeout_s


def _is_stalled(last_activity: float, idle_timeout_s: int | None, now: float) -> bool:
    """True when the run has produced no output for longer than idle_timeout_s
    — a likely hang (stalled model/connection). Disabled when idle_timeout_s is
    None or <= 0. This is what stops an unattended run from hanging forever when
    there is no overall timeout."""
    if idle_timeout_s is None or idle_timeout_s <= 0:
        return False
    return (now - last_activity) > idle_timeout_s


_ENV_REF = re.compile(r"\{env:([A-Za-z_][A-Za-z0-9_]*)\}")


def _env_refs_in_config(config_data: dict) -> list[str]:
    """Env var NAMES referenced as ``{env:NAME}`` anywhere in the opencode
    config — these must be forwarded into the sandbox so the provider key
    resolves inside the container. Returns names only (never values)."""
    names: list[str] = []
    seen: set[str] = set()

    def walk(obj) -> None:
        if isinstance(obj, str):
            for name in _ENV_REF.findall(obj):
                if name not in seen:
                    seen.add(name)
                    names.append(name)
        elif isinstance(obj, dict):
            for v in obj.values():
                walk(v)
        elif isinstance(obj, list):
            for v in obj:
                walk(v)

    walk(config_data)
    return names


def build_run_command(
    cfg: OpenCodeCfg,
    *,
    workdir: str,
    model: str,
    user_message: str,
    config_data: dict,
) -> list[str]:
    """Build the argv to run one task.

    ``sandbox.mode == 'none'`` → run the opencode binary directly on the host
    (unchanged). ``'container'`` → wrap it in ``<runtime> run --rm`` with ONLY
    the run workdir bind-mounted, so the host filesystem (original sources,
    reference solution, other checkouts) is invisible. Env vars the provider
    config references via ``{env:NAME}`` are forwarded by name so the key
    resolves inside the container. Pure (no I/O) for unit testing.
    """
    sb = cfg.sandbox
    container = sb.mode == "container"
    run_dir = sb.workdir_mount if container else workdir
    inner = [
        cfg.binary, "run",
        "--format", "json",
        "--print-logs",
        "--log-level", "INFO",
        "--dir", run_dir,
        "--model", model,
        "--agent", cfg.agent,
        "--dangerously-skip-permissions",
        user_message,
    ]
    if not container:
        return inner

    argv = [
        sb.runtime, "run", "--rm",
        "-v", f"{workdir}:{sb.workdir_mount}",
        "-w", sb.workdir_mount,
    ]
    if sb.network:
        argv += ["--network", sb.network]
    seen: set[str] = set()
    for name in [*_env_refs_in_config(config_data), *sb.env_passthrough]:
        if name not in seen:
            seen.add(name)
            argv += ["-e", name]
    for mount in sb.cache_mounts:
        argv += ["-v", expand_env_refs(mount)]
    argv.append(sb.image)
    argv += inner
    return argv


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
        timeout_s: int | None,
        on_event: Callable[[dict], None],
        log_sink: Callable[[str], None] | None = None,
        debug_sink: Callable[[str], None] | None = None,
        cancel_event: "threading.Event | None" = None,
    ) -> RunResult:
        ...


class RealOpenCodeClient:
    """Drive ``opencode run`` as a subprocess and produce a normalized :class:`Trace`.

    System-prompt handling — Approach A (workdir-local config):
    ---------------------------------------------------------------------------
    Before each run, a file ``opencode.json`` is written into *workdir*.  It
    defines a custom named agent (``cfg.agent``) whose ``prompt`` key carries
    the caller-supplied *system_prompt*, pins ``model``, and defaults
    ``small_model`` to that SAME model (overridable via ``OpenCodeCfg``) so the
    bench uses one provider — the one the operator's interactive opencode
    already reaches — instead of injecting an opencode-native gateway a
    corporate proxy may forbid.

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

    def __init__(self, cfg: OpenCodeCfg, timeout_s: int | None = None) -> None:
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
        timeout_s: int | None,
        on_event: Callable[[dict], None],
        log_sink: Callable[[str], None] | None = None,
        debug_sink: Callable[[str], None] | None = None,
        cancel_event: "threading.Event | None" = None,
    ) -> RunResult:
        def _safe(sink: "Callable[[str], None] | None", line: str) -> None:
            # A log-write failure (e.g. disk full) must never crash the run.
            if sink is not None:
                try:
                    sink(line)
                except Exception:
                    pass

        def readable(line: str) -> None:
            """A concise, human/LLM-readable line → operator console + the
            readable run.log + debug.log (which is a superset of run.log)."""
            _log(line)
            _safe(log_sink, line)
            _safe(debug_sink, line)

        def firehose(line: str) -> None:
            """Verbose opencode output → debug.log ONLY, so the console and the
            readable run.log stay scannable."""
            _safe(debug_sink, line)

        # ── Approach A: write workdir-local config ────────────────────────
        workdir_path = Path(workdir)
        config_data = build_opencode_config(
            self._cfg, model, system_prompt
        )
        (workdir_path / "opencode.json").write_text(
            json.dumps(config_data, indent=2), encoding="utf-8"
        )

        # ── Spawn subprocess (optionally wrapped in a sandbox container) ───
        started_at = time.time()
        cmd = build_run_command(
            self._cfg,
            workdir=workdir,
            model=model,
            user_message=user_message,
            config_data=config_data,
        )
        if self._cfg.sandbox.mode == "container":
            readable(f"[abench] $ {self._cfg.sandbox.runtime} run --rm "
                     f"-v {workdir}:{self._cfg.sandbox.workdir_mount} … "
                     f"{self._cfg.sandbox.image} opencode run …")
        else:
            readable(f"[abench] $ {' '.join(cmd[:6])} … (cwd={workdir})")

        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=workdir,
            env=os.environ.copy(),
        )

        raw_events: list[dict] = []
        interrupted_reason: str | None = None
        # Last time the subprocess produced ANY output (stdout event or stderr
        # line). A one-element list so the reader threads can update it under the
        # GIL without nonlocal. Drives the idle (no-progress) watchdog below.
        last_activity = [started_at]

        def _read_stdout() -> None:
            """Read stdout line by line; parse JSONL; call on_event live and
            print a one-line summary so the operator can see progress."""
            assert proc.stdout is not None
            for line in proc.stdout:
                last_activity[0] = time.time()
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
                    readable(summary)
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
                    last_activity[0] = time.time()
                    text = raw.decode("utf-8", errors="replace").rstrip()
                    if text:
                        firehose(f"  [opencode] {text}")
            except Exception:
                pass

        reader = threading.Thread(target=_read_stdout, daemon=True)
        reader.start()
        stderr_drainer = threading.Thread(target=_drain_stderr, daemon=True)
        stderr_drainer.start()

        # Wait for the process to finish, polling every ≤0.5s so a cancel_event
        # kills the subprocess promptly (cooperative cancel). A deadline of None
        # means no overall time limit — but the idle watchdog still kills a run
        # that goes silent for idle_timeout_s (a likely hang), so an unattended
        # experiment never wedges forever on one stalled run.
        deadline = _run_deadline(started_at, timeout_s)
        idle_timeout_s = self._cfg.idle_timeout_s
        while True:
            if cancel_event is not None and cancel_event.is_set():
                proc.kill()
                interrupted_reason = "cancelled"
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    pass
                break
            if _is_stalled(last_activity[0], idle_timeout_s, time.time()):
                idle = time.time() - last_activity[0]
                readable(f"[abench] no output for {idle:.0f}s — treating the run "
                         f"as stalled and stopping it")
                proc.kill()
                interrupted_reason = "stalled"
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    pass
                break
            if deadline is not None and time.time() >= deadline:
                proc.kill()
                interrupted_reason = "timeout"
                try:
                    proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    pass
                break
            poll = 0.5 if deadline is None else min(0.5, deadline - time.time())
            try:
                proc.wait(timeout=max(0.05, poll))
                break  # finished naturally
            except subprocess.TimeoutExpired:
                continue

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

        readable(f"[abench] opencode returncode={returncode} "
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
