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
    augment_for_authoritative_run,
    augment_for_full_run,
    detect_command as _detect_verify,
    probe_contamination_override,
    run_verify,
    undercount_override,
    write_verify_log,
)

ClientFactory = Callable[[Experiment], OpenCodeClient]


def default_batch_id() -> str:
    """Timestamped batch id (UTC), e.g. ``20260602-143015``."""
    return _datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")


def _baseline_expected(exp: Experiment) -> "int | None":
    """Full suite size from the experiment's cached baseline verify.

    The rcc prefix used to learn this by running the whole suite once per rep
    BEFORE the agent touched anything — cost charged to the treatment arm that the
    autonomous baseline never pays. The cache already knows it, so the autonomous
    path reads it instead of re-measuring. None when no cache exists (the
    undercount guard then simply does not fire)."""
    try:
        cache = exp.fixture_path.parent / ".verify-baseline.json"
        data = json.loads(cache.read_text())
        n = data.get("passed_count")
        return int(n) if isinstance(n, int) and n > 0 else None
    except (OSError, ValueError, AttributeError):
        return None


def _load_coverage(impact_dir) -> dict:
    """Tolerant read of .impact/coverage.json for the rcc llm-builder hint; {} on absence."""
    try:
        return json.loads((Path(impact_dir) / "coverage.json").read_text())
    except (OSError, ValueError):
        return {}


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


def _runtime_probe_jar() -> "str | None":
    """The host-built runtime-evidence agent jar (Plan 1/2). Built via:
        cd docker/runtime-probe && gradle jar
    Returns the absolute path if present, else None (→ phased_runtime degrades to
    plain phased, logged). The phased suite runs host-side, so the jar must be
    built on the host (the sandbox image bakes its own copy for sandboxed runs)."""
    jar = (Path(__file__).resolve().parent.parent
           / "docker" / "runtime-probe" / "build" / "libs" / "runtime-probe-agent.jar")
    return str(jar) if jar.is_file() else None


def _select_orchestrator(cond=None):
    """Pick the phased orchestrator implementation. Precedence: the
    ABENCH_ORCHESTRATOR env var (global override, back-compat) wins; else the
    condition's `engine`; default the Python run(). Lazy imports so the default
    path doesn't require langgraph."""
    engine = (os.environ.get("ABENCH_ORCHESTRATOR")
              or (cond.engine if cond is not None else None) or "python")
    if engine == "langgraph":
        from .orchestrator_graph import run_graph
        return run_graph
    from .orchestrator import run as _run_py
    return _run_py


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


def _preflight_env(exp: Experiment, *, isolated: bool = False) -> None:
    """Raise a single, oriented error if any required host env var OR local
    library path is missing — BEFORE the slow startup or any run.

    ``isolated`` (exposed/LAN UI): provider API keys arrive per-session from the
    session store — not env/auth.json — so don't warn that they're "missing"."""
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
            if isolated:
                continue      # key is provided per-session via the exposed UI
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
    context_window: "int | None" = None,
    isolated: bool = False,
) -> Path:
    # `progress` carries fine-grained setup status for the UI during the
    # otherwise-silent startup window (baseline verify, workdir prep, 429
    # backoff). It is optional so the CLI path is unaffected; default to no-op.
    emit = progress or (lambda _payload: None)

    # Fail fast on a misconfigured environment: resolve every {env:NAME} the run
    # needs on the host BEFORE the (slow) image build / baseline verify, so a
    # missing OS env var surfaces as one clear up-front error rather than a
    # cryptic ValueError minutes into the first run.
    _preflight_env(exp, isolated=isolated)

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

    # Model context window (for the UI's "% of context used"): the explicit
    # override, else a best-effort fetch from the endpoint's /v1/models — resolved
    # ONCE here (caller may pass a pre-resolved value to avoid a duplicate fetch).
    if context_window is None:
        from .model_limits import resolve_context_window
        context_window = resolve_context_window(exp)
        if context_window:
            _log(f"[abench] model context window: {context_window} tokens")

    # Resolve overlay_env once before any run starts — fail-fast on missing host env.
    overlay_env = {k: expand_env_refs(v) for k, v in exp.overlay_env.items()}

    # Benchmark mode: instances + grading come from the adapter, not a local
    # fixture. Route to the benchmark loop, reusing the setup above (client,
    # mcfg, overlay_env, root), and skip the fixture-only baseline-verify + loop.
    if exp.benchmark is not None:
        from .bench.run import run_benchmark
        run_benchmark(exp, client, mcfg, overlay_env, root,
                      emit=emit, cancel_event=cancel_event,
                      context_window=context_window)
        _log(f"[abench] benchmark experiment={exp.name} finished → {root}")
        return root

    plan = _plan if _plan is not None else compute_plan(exp)

    # Baseline pre-flight verify
    if exp.verify.enabled:
        baseline_cache = exp.fixture_path.parent / ".verify-baseline.json"
        _maybe_run_baseline_verify(exp, baseline_cache, emit=emit)

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
                     cancel_event=cancel_event, idx=idx, total=total, progress=emit,
                     context_window=context_window)
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
             progress: "Callable[[dict], None] | None" = None,
             context_window: "int | None" = None) -> None:
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
        system_prompt_eff = cond.system_prompt or exp.system_prompt
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
                # Base = per-condition system-prompt override (or the experiment
                # default), THEN append the per-condition system_augmentation
                # (e.g. forced-instrument lifts the base prompt's "don't touch
                # tests" rule). None/blank on both → experiment prompt unchanged.
                base_system = cond.system_prompt or exp.system_prompt
                _sys_aug = getattr(cond, "system_augmentation", None)
                if _sys_aug and _sys_aug.strip():
                    base_system = f"{(base_system or '').rstrip()}\n\n{_sys_aug.strip()}"
                system_prompt_eff = build_system_prompt(
                    base_system,
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
                    _orchestrate = _select_orchestrator(cond)   # env override | per-condition engine | python

                    suite_cmd = augment_for_full_run(
                        exp.verify.command or _detect_verify(workdir))
                    phase_runner = make_phase_runner(
                        client, workdir=str(workdir),
                        system_prompt=system_prompt_eff, model=exp.model,
                        timeout_s=exp.timeout_s, on_event=on_event,
                        cancel_event=cancel_event, temperature=cond.temperature)
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

                    if cond.orchestration == "rcc":
                        # R1: build the MutationGraph via the seam (artifact loader
                        # primary — a precomputed GT graph.json shipped in the overlay
                        # at .impact/mutation-graph.json; llm fallback), focus() to a
                        # prompt-sized subgraph, then run the phased-identical prefix +
                        # causal loop. Degrades to plain phased if no graph is built.
                        from .git_snapshot import strip_probe_lines_repo
                        from .orchestration_adapters import make_subset_suite_runner
                        from .rcc_graph import RccConfig
                        from .rcc_memory import RccMemory
                        from .rcc_mgraph_build import build_mutation_graph
                        from .rcc_orchestrate import run_rcc_condition
                        ocfg = exp.orchestration
                        from .rcc_mgraph_build import resolve_artifact
                        art = resolve_artifact(workdir / ".impact")   # .json or .json.gz
                        builder = os.environ.get(
                            "ABENCH_RCC_GRAPH_BUILDER",
                            "artifact" if art else "llm")
                        if builder not in ("artifact", "llm", "gt"):
                            _log(f"[abench] rcc: unknown builder '{builder}' — using llm")
                            builder = "llm"
                        if builder == "artifact" and art is None:
                            _log("[abench] rcc: ABENCH_RCC_GRAPH_BUILDER=artifact but no "
                                 ".impact/mutation-graph.json[.gz] — falling back to llm")
                            builder = "llm"
                        if builder == "llm":
                            _log("[abench] rcc: LLM graph builder"
                                 + ("" if art is None else " (artifact present but overridden)"))
                        bkw = ({"artifact_path": art} if builder == "artifact"
                               else {"phase_runner": phase_runner} if builder == "llm"
                               else {"gt_home": os.environ.get("GRAPH_TIPPER_HOME", "")})
                        # A failed build (builder exception, unparseable graph) means
                        # the treatment cannot run. Under rcc_strict (default) that
                        # fails the rep with the reason; otherwise it degrades to plain
                        # phased and the rep is MARKED rcc_degraded.
                        degrade_reason: str | None = None
                        try:
                            mg = build_mutation_graph(
                                workdir, (exp.target_methods or [""])[0],
                                _load_coverage(workdir / ".impact"),
                                builder=builder, **bkw)
                            # NOTE: focus happens in run_rcc_condition once the failing
                            # tests are known (raw graph → target + failing-test callers);
                            # focusing here by class only would leave Alpha rendering
                            # ~950 test-assert edges. Pass the full graph.
                            sub = mg
                        except Exception as exc:
                            sub = None
                            degrade_reason = f"graph build failed: {exc!r}"
                        if sub is None and degrade_reason is None:
                            degrade_reason = "graph builder returned no usable graph"
                        if sub is None:
                            # Without a graph there is no rcc to run. Running plain
                            # PHASED here and still labelling the rep 'rcc' would put
                            # CONTROL behaviour in the TREATMENT arm — biasing the
                            # measured effect toward zero while hiding the pipeline
                            # failure that caused it. Fail loudly by default; the
                            # crash-safety net records the reason and the batch moves on.
                            if ocfg.rcc_strict:
                                raise RuntimeError(
                                    f"rcc: {degrade_reason} (builder={builder}). "
                                    "Refusing to run plain phased under the 'rcc' label "
                                    "— diagnose the graph build, or set "
                                    "orchestration.rcc_strict=false to allow degrading.")
                            _log(f"[abench] rcc: {degrade_reason} — degrading to plain "
                                 "phased (rcc_strict=false); rep marked rcc_degraded")
                            trace = _orchestrate(
                                build_orchestrator_config(exp.orchestration, "phased"),
                                phase_runner=phase_runner, suite_runner=suite_runner,
                                snapshot=lambda: _gsnap(workdir),
                                restore=lambda t: _grestore(workdir, t),
                                on_event=_orch_event, in_blast_radius=None,
                                read_evidence=None, cancel_event=cancel_event)
                            # Mark the TRACE, not just the log: metrics/report/UI and
                            # any A/B aggregate must be able to exclude this rep.
                            trace.rcc_degraded = True
                            trace.rcc_degrade_reason = degrade_reason
                        else:
                            mem_path = (os.environ.get("ABENCH_RCC_MEMORY")
                                        or str(rundir / "rcc-memory.json"))
                            _log(f"[abench] rcc: raw graph {len(sub.methods())} methods, "
                                 f"{sub.classes_total} test classes; builder={builder} "
                                 f"(focus on failing tests happens post-implement); "
                                 f"memory at {mem_path}")
                            trace = run_rcc_condition(
                                build_orchestrator_config(exp.orchestration, "phased"),
                                RccConfig(target_label=ocfg.target_label,
                                          max_attempts=ocfg.rcc_max_attempts,
                                          cluster_cap=ocfg.cluster_cap,
                                          subset_class_cap=ocfg.rcc_subset_class_cap,
                                          revert_to_best=ocfg.rcc_revert_to_best,
                                          first_attempt=ocfg.rcc_first_attempt),
                                sub,
                                phase_runner=phase_runner, suite_runner=suite_runner,
                                subset_runner=make_subset_suite_runner(
                                    workdir, suite_cmd, exp.verify.timeout_s),
                                # Authoritative (--rerun-tasks) runner the prefix
                                # falls back to when implement's incremental suite
                                # under-executes (the Gradle up-to-date false green).
                                full_suite_runner=make_suite_runner(
                                    workdir, augment_for_authoritative_run(suite_cmd),
                                    exp.verify.timeout_s),
                                memory=RccMemory(mem_path),
                                # The autonomous first attempt needs the SAME user
                                # message the baseline arm gets; the cached baseline
                                # size replaces the per-rep pre-edit suite.
                                task_prompt=user_message,
                                baseline_executed=_baseline_expected(exp),
                                strip_probes=lambda: strip_probe_lines_repo(workdir),
                                # revert_to_best: keep the best-reached worktree
                                # (git tree snapshot/restore), gated by config.
                                snapshot=lambda: _gsnap(workdir),
                                restore=lambda t: _grestore(workdir, t),
                                on_event=_orch_event, cancel_event=cancel_event,
                                persist_dir=rundir / "rcc-graph")
                        result = RunResult(trace=trace)
                    else:
                        # phased+graph ablation: a graph-derived "is this failing test
                        # in the target's blast radius?" predicate that focuses the
                        # diagnose loop. Best-effort — None (→ plain phased) if the
                        # .impact coverage data is absent/unmatched.
                        in_blast_radius = None
                        if cond.orchestration == "phased_graph":
                            from .graph_cover import make_blast_radius_predicate
                            in_blast_radius = make_blast_radius_predicate(
                                workdir / ".impact", exp.target_methods or [])

                        # phased+runtime ablation: attach the runtime-evidence probe to
                        # the suite JVM (capture written OUTSIDE the workdir so git
                        # restore can't wipe it between rounds) + feed a diagnostic card
                        # into DIAGNOSE. Best-effort — missing jar/targets degrades to
                        # plain phased (logged), never aborts the run.
                        read_evidence = None
                        if cond.orchestration == "phased_runtime":
                            from .orchestration_adapters import build_evidence_reader
                            jar = _runtime_probe_jar()
                            targets = ",".join(exp.orchestration.probe_targets or [])
                            if jar and targets:
                                cap = str(rundir / "runtime-capture.jsonl")   # OUTSIDE workdir
                                suite_runner = make_suite_runner(
                                    workdir, suite_cmd, exp.verify.timeout_s,
                                    probe={"jar": jar, "targets": targets, "out": cap})
                                read_evidence = build_evidence_reader(
                                    cap, exp.orchestration.target_label)
                                _log(f"[abench] phased_runtime: probe on {targets} -> {cap}")
                            else:
                                _log("[abench] phased_runtime: probe jar/targets missing "
                                     f"(jar={bool(jar)}, targets={bool(targets)}) — plain phased")

                        trace = _orchestrate(
                            build_orchestrator_config(exp.orchestration, cond.orchestration),
                            phase_runner=phase_runner, suite_runner=suite_runner,
                            snapshot=lambda: _gsnap(workdir),
                            restore=lambda t: _grestore(workdir, t),
                            on_event=_orch_event,
                            in_blast_radius=in_blast_radius,
                            read_evidence=read_evidence,
                            cancel_event=cancel_event)
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
                        temperature=cond.temperature,
                    )

                rate_limited = result.trace.interrupted_reason == "rate_limit"
                cancelled = cancel_event is not None and cancel_event.is_set()
                # A session that took ZERO steps after a provider error never began:
                # an authenticating proxy answered 407 before the first turn, so the
                # workdir is untouched and the recorded verdict is about the fixture,
                # not the agent. Retrying that is not a second attempt for the agent —
                # there was no first one — and it is applied identically to every arm.
                # Without it a 407 silently scores the arm it happened to hit, which
                # is how both baseline reps of a picocli A/B came back at 0 steps.
                stillborn = (getattr(result.trace, "n_service_errors", 0)
                             and not result.trace.steps)
                # A session CUT SHORT by a provider error is an invalid sample, not a
                # result: the agent was working (a tool call had just succeeded) when
                # the next model call returned 407, so the recorded cost and verdict
                # describe where the infrastructure interrupted it. Observed pattern —
                # a long tool call (a full gradle suite runs for minutes) leaves the
                # connection idle, and the gateway demands re-auth on the next request.
                #
                # Re-running is a fresh SAMPLE, not an extra attempt for the agent:
                # every attempt in this loop gets a brand-new workdir, so no partial
                # work carries over, and the rule applies identically to both arms.
                # The alternative — scoring it — actively biases whichever arm was
                # unlucky, which is exactly how a picocli A/B came back with baseline
                # 0/2 after the proxy killed both of its reps.
                cut_short = (getattr(result.trace, "n_service_errors", 0)
                             and result.trace.interrupted_reason == "error")

                if ((rate_limited or stillborn or cut_short)
                        and attempt <= exp.rate_limit_retries and not cancelled):
                    backoff = min(
                        exp.rate_limit_backoff_s * (2 ** (attempt - 1)), 120.0
                    )
                    reason = ("rate-limited (429)" if rate_limited
                              else "provider error before the first step" if stillborn
                              else "provider error cut the session short")
                    msg = (
                        f"[abench] {reason} — retry "
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

        # Record the model's context window so the UI can show "% of context used".
        if context_window is not None and result.trace.model_context_window is None:
            result.trace.model_context_window = context_window

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
            # Strip non-target edits (e.g. temporary test instrumentation from
            # the forced-instrument condition) before grading, so the verdict
            # reflects ONLY the agent's target-method implementation. The final
            # diff above (changes.patch) already captured the instrumentation
            # for analysis; this only affects what verify runs against. No-op for
            # conditions whose agent never edits outside target_file (baseline),
            # so it adds no A/B confound.
            cleanup_failed = False
            if (getattr(cond, "restore_non_target_before_verify", False)
                    and exp.target_file and workdir is not None):
                try:
                    from .git_snapshot import restore_except, strip_marked_lines
                    restore_except(workdir, [exp.target_file])
                    # Strip any forgotten //[probe] debug lines from the GRADED
                    # target file (restore_except handles all other files; the
                    # target keeps the agent's edits, so its probes need their
                    # own strip — else a leftover println corrupts stdout-capture
                    # tests at verify).
                    n_probes = strip_marked_lines(workdir, exp.target_file)
                    note("[abench] restored non-target files before verify "
                         f"(test instrumentation stripped; {n_probes} //[probe] "
                         "line(s) stripped from target)")
                except Exception as exc:
                    cleanup_failed = True
                    _log(f"[abench] WARN restore_except/strip failed: {exc!r}")
            # Authoritative grading run: force a FULL re-execution (--rerun-tasks for
            # gradle) so a prior incremental run can't leave modules up-to-date and
            # undercount the suite (the phased "ran 68 of 2437" artifact).
            verify_command = augment_for_authoritative_run(
                exp.verify.command or _detect_verify(workdir))
            if cancelled:
                # Cancelled mid-run, but the agent's PARTIAL diff is real state:
                # verify it like a normal run (real pass-rate on what it got to) and
                # keep the run as a full, analysable data point — flagged truncated
                # via interrupted_reason='cancelled' (+ orchestration_outcome for phased).
                note("[abench] cancelled mid-run — verifying the PARTIAL (truncated) "
                     "diff; run kept + flagged interrupted_reason=cancelled")
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

            # Contamination gate: leftover //[probe] debug lines (the strip failed
            # on a container-owned tree, or the condition never ran one) — or a
            # cleanup step that raised — mean verify's pass/fail reflects probe
            # stdout corrupting capture tests, not the agent's code. Invalidate the
            # MEASUREMENT, same as the undercount guard below. Runs FIRST so its
            # (more actionable) reason wins when both triggers fire. The check is
            # read-only, so it still fires on the very tree whose un-writability
            # defeated the strip in the first place.
            contaminated: list[str] = []
            if (result.trace.verify_status in ("passed", "failed")
                    and workdir is not None):
                try:
                    from .git_snapshot import probe_markers_remaining
                    contaminated = probe_markers_remaining(workdir)
                except Exception:
                    contaminated = []
            _cov = probe_contamination_override(
                result.trace.verify_status, contaminated, cleanup_failed)
            if _cov is not None:
                (result.trace.verify_status, result.trace.verify_reason,
                 result.trace.verify_message) = _cov
                note(f"[abench] {result.trace.verify_message}")

            # Undercount guard: a compiled run that executed far fewer tests than
            # the reference expects is a gradle up-to-date measurement artifact, not
            # a failure — flag it invalid so it's excluded from pass/fail + pass-rate
            # rather than scored ~0 (the phased "0.0238" false-negatives).
            _ov = undercount_override(
                result.trace.verify_status, result.trace.verify_passed_count,
                result.trace.verify_failed_count, result.trace.verify_expected_total)
            if _ov is not None:
                (result.trace.verify_status, result.trace.verify_reason,
                 result.trace.verify_message) = _ov
                note(f"[abench] {result.trace.verify_message}")

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


def _maybe_run_baseline_verify(exp: Experiment, cache_path: Path,
                               emit: "Callable[[dict], None] | None" = None) -> None:
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
    any error skips that side (and the function) without raising. ``emit`` (if
    given) receives fine-grained ``baseline_verify`` progress: one sub-phase per
    side (N/M) plus a throttled tail of the test-tool output, so the UI and log
    show live activity during this otherwise-silent multi-minute window.
    """
    emit = emit or (lambda _payload: None)
    ref_sha = _dir_sha(exp.reference_path)
    fix_sha = _dir_sha(exp.fixture_path)
    cached: dict = {}
    if cache_path.is_file():
        try:
            cached = json.loads(cache_path.read_text())
        except Exception:
            cached = {}
        # Both sides current → nothing to do (fast path; no progress noise).
        if (cached.get("reference_sha") == ref_sha
                and cached.get("fixture_sha") == fix_sha):
            return

    record = dict(cached)

    # Which sides actually need re-running → drives the "N/M" progress labels.
    todo = []
    if cached.get("reference_sha") != ref_sha:
        todo.append("reference")
    if cached.get("fixture_sha") != fix_sha:
        todo.append("fixture")
    total = len(todo)

    def _verify_dir(src: Path, label: str, idx: int):
        """Verify a fresh copy of src, streaming live progress via ``emit``.
        Returns the VerifyResult or None."""
        emit({
            "phase": "baseline_verify",
            "message": (
                f"Baseline verify {idx}/{total}: {label} — running the full test "
                "suite (~2–3 min). One-time; cached in .verify-baseline.json."
            ),
        })
        try:
            workdir, _sha = fx.create_workdir(src)
        except Exception:
            return None
        last = {"t": 0.0}

        def _tail(line: str) -> None:
            line = line.strip()
            if not line:
                return
            _log(f"[baseline-verify:{label}] {line}")
            now = time.time()
            if now - last["t"] < 1.5:          # throttle the UI/WS updates
                return
            last["t"] = now
            emit({
                "phase": "baseline_verify",
                "message": f"Baseline verify {idx}/{total}: {label} · {line[:100]}",
            })

        try:
            command = augment_for_full_run(exp.verify.command or _detect_verify(workdir))
            if command is None:
                return None
            return run_verify(workdir, command, exp.verify.timeout_s, on_line=_tail)
        except Exception:
            return None
        finally:
            fx.cleanup(workdir)

    idx = 0
    # ── Reference side (gold solution) ────────────────────────────────────
    if "reference" in todo:
        idx += 1
        v = _verify_dir(exp.reference_path, "reference (gold)", idx)
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
    if "fixture" in todo:
        idx += 1
        v = _verify_dir(exp.fixture_path, "stripped fixture", idx)
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
    emit({"phase": "baseline_verify", "message": "Baseline verification complete."})


def _dir_sha(path: Path) -> str:
    """Cheap stable hash of a directory tree."""
    h = hashlib.sha1()
    for p in sorted(Path(path).rglob("*")):
        if p.is_file():
            h.update(p.relative_to(path).as_posix().encode())
            h.update(b"\x00")
            h.update(p.read_bytes())
    return h.hexdigest()[:16]
