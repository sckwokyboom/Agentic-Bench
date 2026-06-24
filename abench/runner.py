# abench/runner.py
from __future__ import annotations

import datetime
import hashlib
import json
import os
import random
import re
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime as _datetime, timezone
from pathlib import Path
from typing import Callable

import yaml

from . import fixture as fx
from .config import Condition, Experiment
from .diffstat import parse_diffstat
from .envutil import expand_env_refs
from .methods import best_method_similarity
from .metrics import MetricsConfig, extract
from .opencode_client import OpenCodeClient
from .prompt import build_system_prompt, compose
from .trace_model import FileChange, FinalDiffSummary
from .verify import (
    augment_for_full_run,
    detect_command as _detect_verify,
    run_verify,
    write_verify_log,
)

ClientFactory = Callable[[Experiment], OpenCodeClient]


def default_batch_id() -> str:
    """Timestamped batch id (UTC), e.g. ``20260602-143015``."""
    return _datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def apply_run_subset(
    exp: Experiment,
    conditions: "list[str] | None",
    repetitions: "int | None",
) -> None:
    """Restrict a run to a subset of conditions and/or override the repetition
    count, MUTATING ``exp`` in place. Lets a caller run e.g. just one condition
    x1 from a 4x3 experiment. ``None`` leaves that dimension untouched.

    Raises ValueError on an unknown condition name, an empty selection, or a
    non-positive repetition count — so the API layer can map it to a 400."""
    if conditions is not None:
        known = {c.name for c in exp.conditions}
        unknown = [c for c in conditions if c not in known]
        if unknown:
            raise ValueError(f"unknown condition(s): {', '.join(unknown)}")
        exp.conditions = [c for c in exp.conditions if c.name in conditions]
        if not exp.conditions:
            raise ValueError("no conditions selected")
    if repetitions is not None:
        if repetitions < 1:
            raise ValueError("repetitions must be >= 1")
        exp.repetitions = repetitions


def compute_plan(exp: Experiment) -> list[tuple["Condition", int]]:
    """Build the (condition, rep) execution plan, applying isolation.shuffle_order."""
    plan = [(cond, rep) for cond in exp.conditions for rep in range(exp.repetitions)]
    if exp.isolation.shuffle_order:
        raw = (exp.name + datetime.date.today().isoformat()).encode()
        seed = int(hashlib.sha256(raw).hexdigest()[:16], 16)
        random.Random(seed).shuffle(plan)
    return plan


def _log(msg: str) -> None:
    sys.stderr.write(msg + "\n")
    sys.stderr.flush()


_ENV_REF = re.compile(r"\{env:([A-Za-z_][A-Za-z0-9_]*)\}")


def _required_env_refs(exp: Experiment) -> dict[str, list[str]]:
    """Map each HOST env var the run needs → the config places that reference it.

    A run resolves ``{env:NAME}`` against the OS environment of the *process
    running abench* (CLI shell or the uvicorn server) — never the web UI's form
    fields. Three sources need a host var present before launch:
      * ``sandbox.cache_mounts`` — host-side bind mounts (container mode only;
        in ``mode='none'`` they are never used);
      * ``overlay_env`` values — expanded when rendering overlay ``*.tmpl``;
      * a provider's ``api_key_env`` — the model key, forwarded into the
        container by name (``-e NAME``) or read directly on the host.

    Returning every reference (not just the first) lets the caller fail fast
    with the COMPLETE list instead of dying on one var deep in the first run.
    """
    refs: dict[str, list[str]] = {}

    def add(name: str, where: str) -> None:
        slots = refs.setdefault(name, [])
        if where not in slots:
            slots.append(where)

    if exp.opencode.sandbox.mode == "container":
        for mount in exp.opencode.sandbox.cache_mounts:
            for name in _ENV_REF.findall(mount):
                add(name, "sandbox.cache_mounts")
    for key, value in exp.overlay_env.items():
        for name in _ENV_REF.findall(value):
            add(name, f"overlay_env[{key}]")
    for prov in exp.opencode.providers:
        if prov.api_key_env:
            add(prov.api_key_env, f"provider '{prov.id}' api key")
    return refs


def _required_lib_refs(exp: Experiment) -> dict[str, list[str]]:
    """{lib:NAME} references the run needs resolved from the local registry.
    Mirrors _required_env_refs but for library paths (cache_mounts, overlay_env)."""
    from . import libraries

    refs: dict[str, list[str]] = {}

    def add(name: str, where: str) -> None:
        slots = refs.setdefault(name, [])
        if where not in slots:
            slots.append(where)

    if exp.opencode.sandbox.mode == "container":
        for mount in exp.opencode.sandbox.cache_mounts:
            for name in libraries.lib_names_in(mount):
                add(name, "sandbox.cache_mounts")
    for key, value in exp.overlay_env.items():
        for name in libraries.lib_names_in(value):
            add(name, f"overlay_env[{key}]")
    if exp.opencode.tools_lib:
        add(exp.opencode.tools_lib, "opencode.tools_lib")
    return refs


def _preflight_env(exp: Experiment) -> None:
    """Raise a single, oriented error if any required host env var OR local
    library path is missing — BEFORE the slow startup or any run."""
    from . import libraries

    refs = _required_env_refs(exp)
    missing_env = {n: w for n, w in refs.items() if not os.environ.get(n)}

    # A provider's API key is OPTIONAL — it may be in opencode auth.json
    # (forwarded from there into the run/probe subprocess), or the endpoint may
    # need NO auth at all (a personal/local server). A missing provider key must
    # NOT block the run: run_env then supplies a harmless placeholder so
    # opencode's openai-compatible provider still builds. So drop EVERY provider
    # key from the blocking set; just warn when there is genuinely no key, so a
    # forgotten key for an auth endpoint is still visible (it surfaces as a 401
    # at request time). cache_mounts / overlay_env vars are NOT optional and
    # still block below.
    from . import credentials
    for prov in exp.opencode.providers:
        if prov.api_key_env and prov.api_key_env in missing_env:
            del missing_env[prov.api_key_env]
            if not credentials.has_credential(prov.id):
                _log(f"[abench] WARN provider '{prov.id}' has no API key in env or "
                     f"auth.json — proceeding without auth (a no-auth endpoint, or "
                     f"set a key to authenticate this provider)")

    lib_refs = _required_lib_refs(exp)
    registry = libraries.load_registry()
    missing_lib = {n: w for n, w in lib_refs.items() if n not in registry}

    if not missing_env and not missing_lib:
        return

    parts: list[str] = []
    if missing_env:
        lines = "\n".join(
            f"  - {n}  (used by {', '.join(w)})" for n, w in sorted(missing_env.items()))
        example = " ".join(f"{n}=..." for n in sorted(missing_env))
        parts.append(
            "Missing required environment variable(s):\n" + lines + "\n\n"
            "These are OS environment variables read from the process running "
            "abench — export them in the shell that launches `abench`/`abench-ui` "
            "(NOT the web UI). Example:\n"
            f"  {example} abench run <experiment.yaml>")
    if missing_lib:
        lines = "\n".join(
            f"  - {n}  (used by {', '.join(w)})" for n, w in sorted(missing_lib.items()))
        adds = "\n".join(f"  abench lib add {n} <path>" for n in sorted(missing_lib))
        parts.append(
            "Missing local library path(s) in the registry "
            f"({libraries.FILENAME}):\n" + lines + "\n\nRegister them once:\n" + adds)
    raise RuntimeError("\n\n".join(parts))


# opencode's built-in sub-agent spawners. A sub-agent's individual steps never
# reach our exported trace (so the cheating detector can't audit them) and it
# doesn't inherit the run's grounding guard (so it's unconstrained re: network /
# outside-FS). The bench disables these for every run unless an experiment opts
# in via `opencode.allow_subagents`, keeping each run a single, fully-traced,
# guard-bound agent.
SUBAGENT_TOOLS = ("task",)

# Built-in tools that reach the network / outside world. Disabled when the run
# forbids external sources, so the grounding guard's "no internet" rule is
# enforced at the tool level, not merely requested in the prompt. NOTE: `bash`
# can still curl, so on host-mode runs this is a PARTIAL control — the container
# sandbox is the real network boundary and the cheating detector is the post-hoc
# backstop. This removes the obvious, explicitly-network tool.
NETWORK_TOOLS = ("webfetch",)


def _reclaim_workdir_ownership(sandbox, workdir: str) -> None:
    """Chown the run workdir back to the host user after a container run.

    The agent runs as ROOT inside the sandbox, so any build artifacts it created
    in the bind-mounted workdir (`build/`, `.gradle/`, `target/`) are root-owned
    on the host. That blocks every host-side step that follows: gradle verify
    fails before tests ("Unable to delete directory '<wd>/build/...'"), and
    rmtree cleanup silently leaks them. Reclaim ownership via a throwaway root
    container (`--entrypoint chown` bypasses the image's setup entrypoint).
    Best-effort; NEVER raises. No-op when the agent ran on the host."""
    if sandbox.mode != "container":
        return
    getuid = getattr(os, "getuid", None)
    getgid = getattr(os, "getgid", None)
    if getuid is None or getgid is None:  # non-POSIX host; container mode is Linux
        return
    try:
        subprocess.run(
            [sandbox.runtime, "run", "--rm", "--entrypoint", "chown",
             "-v", f"{workdir}:{sandbox.workdir_mount}",
             sandbox.image, "-R", f"{getuid()}:{getgid()}", sandbox.workdir_mount],
            capture_output=True, timeout=120, check=False)
    except (OSError, subprocess.SubprocessError):
        pass


def _agent_tools_for(exp: Experiment, cond: Condition) -> dict[str, bool] | None:
    """Per-condition OpenCode agent tools map, composing three gates: (a) disable
    every tool the tools_lib ships that this condition does NOT enable, (b)
    disable the built-in sub-agent spawners unless `allow_subagents` is set, and
    (c) disable the built-in network tools when `forbid_external_sources` is on.
    None when no gate has anything to override."""
    gate: dict[str, bool] = {}
    if exp.opencode.tools_lib:
        from . import libraries
        registry = libraries.load_registry()
        lib_path = registry.get(exp.opencode.tools_lib)
        if lib_path:
            universe = libraries.discover_opencode_tools(lib_path)
            enabled = set(cond.tools)
            gate.update({name: (name in enabled) for name in universe})
        # else: unreachable on a configured run (pre-flight requires the
        # tools_lib be registered); defensive — fall through with no GT gate.
    if not exp.opencode.allow_subagents:
        for name in SUBAGENT_TOOLS:
            gate[name] = False
    if exp.isolation.forbid_external_sources:
        for name in NETWORK_TOOLS:
            gate[name] = False
    return gate or None


def _dump_resolved(exp: Experiment) -> str:
    def conv(obj):
        if isinstance(obj, Path):
            return str(obj)
        if isinstance(obj, dict):
            return {k: conv(v) for k, v in obj.items()}
        if isinstance(obj, list):
            return [conv(x) for x in obj]
        return obj
    return yaml.safe_dump(conv(exp.model_dump()), allow_unicode=True, sort_keys=False)


def run_experiment(
    exp: Experiment,
    client_factory: ClientFactory,
    _plan: list[tuple["Condition", int]] | None = None,
    batch_id: str | None = None,
    cancel_event: "threading.Event | None" = None,
    progress: "Callable[[dict], None] | None" = None,
) -> Path:
    # `progress` carries fine-grained setup status for the UI during the
    # otherwise-silent startup window (baseline verify, workdir prep, 429
    # backoff). It is optional so the CLI path is unaffected; default to no-op.
    emit = progress or (lambda _payload: None)

    # Fail fast on a misconfigured environment: resolve every {env:NAME} the run
    # needs on the host BEFORE the (slow) image build / baseline verify, so a
    # missing OS env var surfaces as one clear up-front error rather than a
    # cryptic ValueError minutes into the first run.
    _preflight_env(exp)

    if batch_id is None:
        batch_id = default_batch_id()
    root = exp.output_dir / exp.name / batch_id
    root.mkdir(parents=True, exist_ok=True)
    (root / "experiment.resolved.yaml").write_text(_dump_resolved(exp))

    mcfg = MetricsConfig(**exp.metrics.model_dump())

    # Container sandbox: make sure the image exists before any run (build once
    # if missing) so the operator never has to build anything by hand.
    if exp.opencode.sandbox.mode == "container":
        from .sandbox import ensure_image
        ensure_image(exp.opencode.sandbox, log=_log, progress=emit)

    client = client_factory(exp)

    # Resolve overlay_env once before any run starts — fail-fast on missing host env.
    overlay_env = {k: expand_env_refs(v) for k, v in exp.overlay_env.items()}

    plan = _plan if _plan is not None else compute_plan(exp)

    # Baseline pre-flight verify
    if exp.verify.enabled:
        emit({
            "phase": "baseline_verify",
            "message": (
                "Running baseline verification — checking the reference "
                "solution and the stripped fixture against the tests…"
            ),
        })
        baseline_cache = exp.fixture_path.parent / ".verify-baseline.json"
        _maybe_run_baseline_verify(exp, baseline_cache)

    total = len(plan)
    t_exp = time.time()
    _log(
        f"[abench] experiment={exp.name} model={exp.model} "
        f"total_runs={total} timeout_s={exp.timeout_s} output_dir={root} "
        f"isolation: nonce={exp.isolation.nonce_prefix} shuffle={exp.isolation.shuffle_order}"
    )

    for idx, (cond, rep) in enumerate(plan, start=1):
        if cancel_event is not None and cancel_event.is_set():
            _log("[abench] cancelled — skipping remaining runs")
            break
        _log(
            f"[abench] ───── run {idx}/{total}: condition={cond.name} rep={rep} ─────"
        )
        t_run = time.time()
        try:
            _run_one(exp, cond, rep, root, client, mcfg, overlay_env=overlay_env,
                     cancel_event=cancel_event, idx=idx, total=total, progress=emit)
        except Exception as exc:
            # _run_one already recorded error.log + an errored trace/metrics for
            # this run. Swallow here so ONE crashed run cannot kill the whole
            # batch (and take the aggregate with it); surface it loudly instead.
            import traceback as _tb
            _log(f"[abench] run {idx}/{total} FAILED — recorded to "
                 f"{cond.name}/rep_{rep}/error.log; continuing.\n{_tb.format_exc()}")
            emit({
                "phase": "run_error", "run_idx": idx,
                "condition": cond.name, "rep": rep,
                "message": (f"Run {idx}/{total} crashed ({exc!r}) — recorded to "
                            f"error.log; continuing with the remaining runs."),
            })
        _log(f"[abench] run {idx}/{total} done in {time.time() - t_run:.1f}s")
        if exp.min_seconds_between_runs:
            _log(f"[abench] cooldown {exp.min_seconds_between_runs}s")
            time.sleep(exp.min_seconds_between_runs)
    _log(f"[abench] experiment finished in {time.time() - t_exp:.1f}s → {root}")
    return root


def _run_one(exp: Experiment, cond: Condition, rep: int, root: Path,
             client: OpenCodeClient, mcfg: MetricsConfig,
             overlay_env: "dict[str, str] | None" = None,
             cancel_event: "threading.Event | None" = None,
             idx: int = 0, total: int = 0,
             progress: "Callable[[dict], None] | None" = None) -> None:
    emit = progress or (lambda _payload: None)
    rundir = root / cond.name / f"rep_{rep}"
    rundir.mkdir(parents=True, exist_ok=True)

    # Initialized before the try so the finally is safe even if the first
    # create_workdir (inside the retry loop) raises.
    workdir: Path | None = None
    logf = debugf = None  # closed in the outer finally (after verify/result)
    # Defined before the try so the crash-safety net (the except below) can
    # always reference them, even if a failure happens before the run loop runs.
    sha = ""
    result = None
    try:
        user_message = compose(exp.task_prompt, cond.augmentation)

        # events.jsonl + run.log are opened ONCE and reused across retry
        # attempts: events.jsonl accumulates every attempt's raw events, while
        # trace.json (written after the loop) reflects the FINAL attempt.
        events_file = (rundir / "events.jsonl").open("w")

        def on_event(event: dict) -> None:
            events_file.write(json.dumps(event) + "\n")
            events_file.flush()

        # Two per-run logs:
        #   run.log   — concise + readable (stages, tool/llm one-liners, results,
        #               errors); the default the operator/UI sees and can hand to
        #               an LLM.
        #   debug.log — the full firehose: the readable lines PLUS opencode's
        #               verbose stderr, for diagnosing hangs.
        # Best-effort — a logging failure (e.g. disk full) must never crash the
        # run, so on any open/write error the sink degrades to a no-op.
        def _open_log(fname: str):
            try:
                f = (rundir / fname).open("w")
                f.write(
                    f"# condition: {cond.name}\n"
                    f"# rep: {rep}\n"
                    f"# model: {exp.model}\n"
                    f"# verify_command: {exp.verify.command or '(autodetect)'}\n"
                    "\n"
                )
                f.flush()
                return f
            except Exception:
                return None

        logf = _open_log("run.log")
        debugf = _open_log("debug.log")

        def _sink(f):
            def write(line: str) -> None:
                if f is None:
                    return
                try:
                    f.write(line + "\n")
                    f.flush()
                except Exception:
                    pass
            return write

        readable_sink = _sink(logf)
        debug_sink = _sink(debugf)

        def note(line: str) -> None:
            """A harness line written by the runner itself → both logs."""
            readable_sink(line)
            debug_sink(line)

        # ── Retry-with-backoff loop ───────────────────────────────────
        # Each attempt gets a FRESH workdir (→ new sha → new nonce header).
        # We retry ONLY when the run ended rate-limited (429) and retries
        # remain and we haven't been cancelled.
        nonce: str | None = None
        system_prompt_eff = exp.system_prompt
        sha = ""
        result = None
        agent_tools = _agent_tools_for(exp, cond)
        try:
            for attempt in range(1, exp.rate_limit_retries + 2):
                emit({
                    "phase": "preparing_workdir",
                    "run_idx": idx, "condition": cond.name, "rep": rep,
                    "message": (
                        "Preparing an isolated workdir — copying the project "
                        "and initializing git…"
                    ),
                })
                workdir, sha = fx.create_workdir(
                    exp.fixture_path,
                    overlay_dir=cond.overlay,
                    overlay_env=overlay_env,
                )

                # Isolation: grounding guard + nonce-prefix in system_prompt
                # (rebuilt per attempt so each gets a fresh nonce).
                nonce = uuid.uuid4().hex if exp.isolation.nonce_prefix else None
                system_prompt_eff = build_system_prompt(
                    exp.system_prompt,
                    nonce=nonce,
                    fixture_sha=sha,
                    forbid_external_sources=exp.isolation.forbid_external_sources,
                )

                if cond.orchestration and exp.orchestration is not None:
                    # Phased-orchestration condition: a controller drives opencode
                    # per phase (UNDERSTAND→[PLAN]→IMPLEMENT→DIAGNOSE) on this
                    # workdir and returns one stitched Trace. Downstream (diff,
                    # trace.json, verify, metrics) is unchanged.
                    from .git_snapshot import restore as _grestore
                    from .git_snapshot import snapshot as _gsnap
                    from .opencode_client import RunResult
                    from .orchestration_adapters import (
                        build_orchestrator_config,
                        make_phase_runner,
                        make_suite_runner,
                    )
                    from .orchestrator import run as _orchestrate

                    suite_cmd = augment_for_full_run(
                        exp.verify.command or _detect_verify(workdir))
                    phase_runner = make_phase_runner(
                        client, workdir=str(workdir),
                        system_prompt=system_prompt_eff, model=exp.model,
                        timeout_s=exp.timeout_s, on_event=on_event)
                    suite_runner = make_suite_runner(
                        workdir, suite_cmd, exp.verify.timeout_s)

                    # VISUALIZATION-ONLY sink: stream the orchestrator's phase
                    # hand-offs + controller actions to the live UI (via the
                    # client wrapper's control_event), if the client provides it.
                    # Never touches events.jsonl or metrics — purely for the live
                    # view, so it can't affect the cross-trace comparison.
                    _control_event = getattr(client, "control_event", None)

                    def _orch_event(ev: dict) -> None:
                        if _control_event is not None:
                            try:
                                _control_event(ev)
                            except Exception:
                                pass

                    trace = _orchestrate(
                        build_orchestrator_config(exp.orchestration, cond.orchestration),
                        phase_runner=phase_runner, suite_runner=suite_runner,
                        snapshot=lambda: _gsnap(workdir),
                        restore=lambda t: _grestore(workdir, t),
                        on_event=_orch_event)
                    result = RunResult(trace=trace)
                else:
                    result = client.run_task(
                        workdir=str(workdir),
                        system_prompt=system_prompt_eff,
                        model=exp.model,
                        user_message=user_message,
                        timeout_s=exp.timeout_s,
                        agent_tools=agent_tools,
                        on_event=on_event,
                        log_sink=readable_sink,
                        debug_sink=debug_sink,
                        cancel_event=cancel_event,
                    )

                rate_limited = result.trace.interrupted_reason == "rate_limit"
                cancelled = cancel_event is not None and cancel_event.is_set()

                if rate_limited and attempt <= exp.rate_limit_retries and not cancelled:
                    backoff = min(
                        exp.rate_limit_backoff_s * (2 ** (attempt - 1)), 120.0
                    )
                    msg = (
                        f"[abench] rate-limited (429) — retry "
                        f"{attempt}/{exp.rate_limit_retries} after {backoff:.0f}s"
                    )
                    _log(msg)
                    note(msg)
                    emit({
                        "phase": "rate_limit_backoff",
                        "run_idx": idx, "condition": cond.name, "rep": rep,
                        "retry": attempt, "max_retries": exp.rate_limit_retries,
                        "backoff_s": backoff,
                        "message": (
                            f"Rate limited (429) — waiting {backoff:.0f}s before "
                            f"retry {attempt}/{exp.rate_limit_retries}…"
                        ),
                    })
                    fx.cleanup(workdir)
                    workdir = None
                    # Cancellable backoff: sleep in ≤0.5s steps, breaking early
                    # if a cancel is requested.
                    slept = 0.0
                    while slept < backoff:
                        if cancel_event is not None and cancel_event.is_set():
                            break
                        step = min(0.5, backoff - slept)
                        time.sleep(step)
                        slept += step
                    continue
                break
        finally:
            # Keep run.log/debug.log open through verify + the result line below;
            # they are closed in the outer finally.
            events_file.close()

        # Record isolation nonce on the trace
        if nonce is not None:
            result.trace.isolation_nonce = nonce

        # The agent ran as root in the sandbox; reclaim ownership of the workdir
        # so the host-side diff/verify/cleanup below can manage its (otherwise
        # root-owned) build artifacts. No-op in host mode.
        if workdir is not None:
            _reclaim_workdir_ownership(exp.opencode.sandbox, str(workdir))

        # ── Final diff + per-file summary ────────────────────────────
        patch = fx.diff_workdir(workdir)
        (rundir / "changes.patch").write_text(patch)
        _, added, removed = parse_diffstat(patch)
        per_file = _per_file_diffstat(patch)
        result.trace.final_diff_summary = FinalDiffSummary(
            files=[FileChange(path=p, added=a, removed=r) for (p, a, r) in per_file],
            total_added=added,
            total_removed=removed,
        )
        note(f"[abench] changes: +{added}/-{removed} across {len(per_file)} file(s)")

        # ── Output-similarity to the reference (cheating 'output≈original') ──
        if exp.target_file and exp.target_methods and workdir is not None:
            try:
                ref_text = (exp.reference_path / exp.target_file).read_text(encoding="utf-8")
                agent_text = (workdir / exp.target_file).read_text(encoding="utf-8")
                result.trace.target_similarity = best_method_similarity(
                    ref_text, agent_text, exp.target_file, exp.target_methods)
            except Exception:
                pass

        # ── Trace.json + metrics ─────────────────────────────────────
        (rundir / "trace.json").write_text(json.dumps(result.trace.to_dict(), indent=2))
        metrics = extract(result.trace, patch, mcfg)
        (rundir / "metrics.json").write_text(json.dumps(metrics, indent=2))

        # ── Verify (post-rep, before cleanup) ────────────────────────
        if exp.verify.enabled:
            verify_command = augment_for_full_run(
                exp.verify.command or _detect_verify(workdir))
            if verify_command is None:
                result.trace.verify_status = "skipped"
            else:
                try:
                    v = run_verify(workdir, verify_command, exp.verify.timeout_s)
                    result.trace.verify_status = v.status
                    result.trace.verify_command = v.command
                    result.trace.verify_duration_s = v.duration_s
                    result.trace.verify_passed_count = v.passed_count
                    result.trace.verify_failed_count = v.failed_count
                    result.trace.verify_failed_names = v.failed_names
                    result.trace.verify_reason = v.reason
                    result.trace.verify_message = v.message
                    write_verify_log(rundir, v)
                except Exception as exc:
                    _log(f"[abench] WARN verify raised unexpectedly: {exc!r}")
                    note(f"[abench] WARN verify raised unexpectedly: {exc!r}")
                    result.trace.verify_status = "error"
                    result.trace.verify_command = verify_command
                    result.trace.verify_reason = "unparseable"
                    result.trace.verify_message = f"verify raised unexpectedly: {exc!r}"

            # Check baseline cache and propagate sensitivity flags.
            baseline_cache = exp.fixture_path.parent / ".verify-baseline.json"
            if baseline_cache.is_file():
                try:
                    baseline = json.loads(baseline_cache.read_text())
                    if baseline.get("status") != "passed":
                        result.trace.verify_baseline_unknown = True
                    # Stripped fixture already passes the same tests → pass/fail
                    # cannot reflect agent work.
                    result.trace.verify_insensitive = (
                        baseline.get("fixture_status") == "passed")
                    # Full expected suite size = the reference's passing count
                    # (only trustworthy when the reference itself verified green).
                    if baseline.get("status") == "passed" and baseline.get("passed_count"):
                        result.trace.verify_expected_total = baseline["passed_count"]
                except Exception:
                    pass

            note(
                f"[abench] verify: {result.trace.verify_status} "
                f"passed={result.trace.verify_passed_count} "
                f"failed={result.trace.verify_failed_count} "
                f"cmd={result.trace.verify_command}"
            )

            # Re-serialise trace.json with verify_* populated
            (rundir / "trace.json").write_text(json.dumps(result.trace.to_dict(), indent=2))
            # Refresh metrics (verify_* propagate via metrics.extract)
            metrics = extract(result.trace, patch, mcfg)
            (rundir / "metrics.json").write_text(json.dumps(metrics, indent=2))

        # Snapshot target_file (if configured) so /method_comparison can read it later.
        if exp.target_file:
            target_src = workdir / exp.target_file
            if target_src.is_file():
                target_dst = rundir / "target_after_agent.txt"
                target_dst.write_text(target_src.read_text(), encoding="utf-8")

        tr = result.trace
        result_line = (
            f"[abench] result: finished={tr.finished} "
            f"reason={tr.interrupted_reason} steps={len(tr.steps)} "
            f"tokens_in={tr.tokens_in} tokens_out={tr.tokens_out} "
            f"verify={tr.verify_status}"
        )
        _log(result_line)
        note(result_line)
        if tr.verify_status not in (None, "passed", "skipped"):
            warn = (
                f"[abench] WARN verify={tr.verify_status} "
                f"cmd={tr.verify_command} failed={tr.verify_failed_count}"
            )
            _log(warn)
            note(warn)
        (rundir / "manifest.json").write_text(json.dumps({
            "condition": cond.name,
            "rep": rep,
            "model": exp.model,
            "fixture_sha": sha,
            "user_message": user_message,
        }, indent=2))
    except Exception as exc:
        # ── Crash-safety net ─────────────────────────────────────────
        # A failure anywhere above (orchestration, the sandbox/docker launch,
        # diff, verify, …) must NOT vanish: without this the run dir is empty
        # (no trace.json/metrics.json) and the only signal is the batch dying —
        # "0 information". Record the full traceback + an errored trace/metrics/
        # manifest so the run is SAVED, visible in the UI, and counted by the
        # aggregate, then re-raise for the batch loop to log-and-continue. Every
        # write here is best-effort — this handler must never raise.
        import traceback as _tb

        from .trace_model import Trace as _Trace
        tb_text = _tb.format_exc()
        try:
            (rundir / "error.log").write_text(
                f"# condition: {cond.name}\n# rep: {rep}\n# model: {exp.model}\n"
                f"# fixture_sha: {sha}\n# error: {exc!r}\n\n{tb_text}\n",
                encoding="utf-8")
        except Exception:
            pass
        try:
            _log(f"[abench] FATAL run crashed cond={cond.name} rep={rep}: {exc!r}")
        except Exception:
            pass
        try:
            note(f"[abench] FATAL run crashed: {exc!r}\n{tb_text}")  # noqa: F821
        except Exception:
            pass
        try:
            tr = result.trace if result is not None else _Trace()
            tr.finished = False
            tr.interrupted_reason = "error"
            tr.service_error_messages = list(tr.service_error_messages or []) + [
                f"harness crash: {exc!r}"]
            (rundir / "trace.json").write_text(json.dumps(tr.to_dict(), indent=2))
            try:
                metrics = extract(tr, "", mcfg)
            except Exception:
                metrics = {}
            metrics["finished"] = False
            metrics["interrupted_reason"] = "error"
            metrics["error"] = repr(exc)
            (rundir / "metrics.json").write_text(json.dumps(metrics, indent=2))
        except Exception:
            pass
        try:
            (rundir / "manifest.json").write_text(json.dumps({
                "condition": cond.name, "rep": rep, "model": exp.model,
                "fixture_sha": sha, "error": repr(exc),
            }, indent=2))
        except Exception:
            pass
        raise
    finally:
        # Close the per-run logs here (kept open through verify + the result
        # line so those land in the readable log too).
        for f in (logf, debugf):
            if f is not None:
                f.close()
        # Intermediate retried workdirs are cleaned in the loop and set to
        # None; only the final (or a never-created) workdir remains here.
        if workdir is not None:
            fx.cleanup(workdir)


def _diff_header_path(line: str) -> str | None:
    """Extract the 'a/<path>' file from a 'diff --git …' header. Handles git's
    quoting of paths with special/non-ASCII chars, e.g.
    'diff --git "a/naïve.txt" "b/naïve.txt"' — without this such an edit would
    be missed and a real change would look like "no source changes"."""
    rest = line[len("diff --git "):]
    if rest.startswith('"'):
        end = rest.find('"', 1)
        token = rest[1:end] if end != -1 else rest[1:]
    else:
        sep = rest.rfind(" b/")
        token = rest[:sep] if sep != -1 else rest.split(" ", 1)[0]
    return token[2:] if token.startswith("a/") else (token or None)


def _per_file_diffstat(patch: str) -> list[tuple[str, int, int]]:
    """Return [(path, added, removed)] from a unified git diff."""
    files: list[tuple[str, int, int]] = []
    current: str | None = None
    added = 0
    removed = 0
    for line in patch.splitlines():
        if line.startswith("diff --git "):
            if current is not None:
                files.append((current, added, removed))
            current = _diff_header_path(line)
            added = removed = 0
        elif line.startswith("+++ ") or line.startswith("--- "):
            continue
        elif line.startswith("+"):
            added += 1
        elif line.startswith("-"):
            removed += 1
    if current is not None:
        files.append((current, added, removed))
    return files


def _maybe_run_baseline_verify(exp: Experiment, cache_path: Path) -> None:
    """Best-effort baseline verify; caches result in cache_path.

    Verifies BOTH:
      * a fresh copy of ``reference_path`` (the gold solution should PASS) —
        cached as ``status``/``reference_sha`` (back-compat keys), and
      * a fresh copy of the STRIPPED ``fixture_path`` (the starting point the
        agent receives). If the stripped fixture already PASSES the same tests
        the runner runs, then per-run pass/fail cannot reflect agent work —
        cached as ``fixture_status``/``fixture_sha`` and surfaced per-run as
        ``verify_insensitive``.

    Each side re-runs only when its dir sha mismatches the cache. Best-effort:
    any error skips that side (and the function) without raising.
    """
    ref_sha = _dir_sha(exp.reference_path)
    fix_sha = _dir_sha(exp.fixture_path)
    cached: dict = {}
    if cache_path.is_file():
        try:
            cached = json.loads(cache_path.read_text())
        except Exception:
            cached = {}
        # Both sides current → nothing to do.
        if (cached.get("reference_sha") == ref_sha
                and cached.get("fixture_sha") == fix_sha):
            return

    record = dict(cached)

    def _verify_dir(src: Path):
        """Verify a fresh copy of src; return the VerifyResult or None."""
        try:
            workdir, _sha = fx.create_workdir(src)
        except Exception:
            return None
        try:
            command = augment_for_full_run(exp.verify.command or _detect_verify(workdir))
            if command is None:
                return None
            return run_verify(workdir, command, exp.verify.timeout_s)
        except Exception:
            return None
        finally:
            fx.cleanup(workdir)

    # ── Reference side (gold solution) ────────────────────────────────────
    if cached.get("reference_sha") != ref_sha:
        v = _verify_dir(exp.reference_path)
        if v is not None:
            record.update({
                "command": exp.verify.command or v.command,
                "reference_sha": ref_sha,
                "status": v.status, "reason": v.reason, "message": v.message,
                "passed_count": v.passed_count, "failed_count": v.failed_count,
            })
            try:
                write_verify_log(cache_path.parent, v)
                (cache_path.parent / "verify_output.log").rename(
                    cache_path.parent / ".verify-baseline-output.log")
            except Exception:
                pass

    # ── Fixture side (stripped starting point) ────────────────────────────
    if cached.get("fixture_sha") != fix_sha:
        v = _verify_dir(exp.fixture_path)
        if v is not None:
            record.update({
                "fixture_sha": fix_sha,
                "fixture_status": v.status,
                "fixture_reason": v.reason,
                "fixture_passed_count": v.passed_count,
                "fixture_failed_count": v.failed_count,
            })

    if record:
        try:
            cache_path.write_text(json.dumps(record))
        except Exception:
            pass


def _dir_sha(path: Path) -> str:
    """Cheap stable hash of a directory tree."""
    h = hashlib.sha1()
    for p in sorted(Path(path).rglob("*")):
        if p.is_file():
            h.update(p.relative_to(path).as_posix().encode())
            h.update(b"\x00")
            h.update(p.read_bytes())
    return h.hexdigest()[:16]
