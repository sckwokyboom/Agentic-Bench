"""Real adapters wiring orchestrator.run into the runner.

- `phase_runner`: one opencode `run_task` per phase, same workdir, scoped tools.
- `suite_runner`: the host test command + JUnit XML (same approach as verify.py),
  yielding a full SuiteResult breakdown (compiled/ran/executed/passed/failed/
  errors/skipped) + the per-test failures for clustering.
- `build_orchestrator_config`: OrchestratorConfig from experiment config + mode.

The PURE pieces (XML eval, phase-text extraction, config build) are unit-tested
here; the thin subprocess / opencode wrappers are validated on the real box.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Callable

from .failure_report import parse_junit_dir
from .orchestrator import OrchestratorConfig, PhaseOutcome, SuiteEval
from .regression_gate import SuiteResult
from .trace_model import Step, StepKind, Trace

# Markers of a *compilation* failure specifically. Deliberately NOT "BUILD
# FAILED" or "error:" — gradle/maven print those whenever any *test* fails too,
# so matching them flags a compiling, test-running suite as "does not compile".
# Matched case-insensitively against the combined stdout+stderr.
_COMPILE_MARKERS = (
    "compilation error",        # Maven
    "cannot find symbol",       # javac
    "compilation failed",       # gradle ("Compilation failed; see ...")
    "compilejava failed",       # gradle task ("> Task :compileJava FAILED")
    "compiletestjava failed",   # gradle task (test sources)
)


def build_status(out: str, executed: int) -> tuple[bool, bool]:
    """Derive (compiled, ran) from the combined test output and the number of
    tests that executed.

    If ANY test executed, compilation necessarily succeeded — so a "BUILD FAILED"
    (which gradle/maven print whenever a *test* fails) is NOT a compile error.
    Only when nothing executed do compile-specific markers distinguish a real
    compile failure from an infra/no-tests problem (timeout, wrong command). In
    the latter case we report compiled=True, ran=False: we can't prove a compile
    failure, so we don't claim one — the gate still rejects on ran=False.
    """
    if executed > 0:
        return True, True
    has_compile_err = any(m in out.lower() for m in _COMPILE_MARKERS)
    return (not has_compile_err), False


def _toint(v: "str | None") -> int:
    """Parse a JUnit count attribute; 0 on missing/non-numeric (a corrupt XML
    must not crash the whole suite eval)."""
    try:
        return int(v or 0)
    except (TypeError, ValueError):
        return 0


def eval_from_junit(results_dir: Path, *, compiled: bool = True, ran: bool = True) -> SuiteEval:
    """Aggregate JUnit XML under results_dir into a SuiteEval (full count
    breakdown + per-test failures). compiled/ran reflect the build outcome."""
    results_dir = Path(results_dir)
    tests = failures = errors = skipped = 0
    found = False
    for xml in results_dir.rglob("TEST-*.xml"):
        try:
            root = ET.fromstring(xml.read_text())
        except (OSError, ET.ParseError):
            continue
        suites = [root] if root.tag == "testsuite" else list(root.iter("testsuite"))
        for ts in suites:
            found = True
            tests += _toint(ts.get("tests"))
            failures += _toint(ts.get("failures"))
            errors += _toint(ts.get("errors"))
            skipped += _toint(ts.get("skipped"))
    failed = failures + errors
    passed = max(0, tests - failed - skipped)
    result = SuiteResult(compiled=compiled, ran=ran and found, executed=tests,
                         passed=passed, failed=failed, errors=errors, skipped=skipped)
    return SuiteEval(result=result, failures=parse_junit_dir(results_dir))


def _clear_results(workdir: Path) -> None:
    for d in Path(workdir).glob("**/build/test-results"):
        shutil.rmtree(d, ignore_errors=True)


def make_suite_runner(workdir: Path, command: str, timeout_s: int,
                      probe: "dict | None" = None) -> Callable[[], SuiteEval]:
    """Host subprocess (like verify) + JUnit XML breakdown. Clears stale results
    first so each call reflects only its own run.

    When ``probe`` is given (keys: ``jar``, ``targets``, ``out``), attaches the
    runtime-evidence agent to the forked test JVM via JAVA_TOOL_OPTIONS and clears
    the capture file beforehand, so each call's capture reflects only its own run.
    The capture path should live OUTSIDE the workdir (git restore/clean would wipe
    an in-workdir capture between diagnose rounds)."""
    workdir = Path(workdir)

    def runner() -> SuiteEval:
        _clear_results(workdir)
        env = dict(os.environ)
        if probe:
            try:
                Path(probe["out"]).unlink()          # fresh capture per run
            except OSError:
                pass
            env["JAVA_TOOL_OPTIONS"] = (
                env.get("JAVA_TOOL_OPTIONS", "")
                + f" -javaagent:{probe['jar']}={probe['targets']}"
                + f" -Druntime.probe.out={probe['out']}").strip()
        try:
            proc = subprocess.run(command, shell=True, cwd=workdir,
                                  capture_output=True, text=True, timeout=timeout_s,
                                  env=env)
            out = (proc.stdout or "") + "\n" + (proc.stderr or "")
        except (subprocess.TimeoutExpired, OSError):
            # timeout, or the test command can't be spawned (binary/cwd gone) —
            # report "couldn't run" so the orchestrator's gate rejects the round
            # rather than the whole run aborting.
            return SuiteEval(result=SuiteResult(compiled=True, ran=False, executed=0,
                                                passed=0, failed=0))
        # #executed (from JUnit XML) is the ground truth for "did it compile?":
        # you cannot run tests without compiling. Derive compiled/ran from that
        # first, falling back to compile-marker matching only when nothing ran.
        ev = eval_from_junit(workdir, compiled=True, ran=True)
        compiled, ran = build_status(out, ev.result.executed)
        ev.result.compiled = compiled
        ev.result.ran = ran
        return ev

    return runner


def build_evidence_reader(capture_path, target_label: str) -> "Callable[[], str | None]":
    """A read_evidence() the orchestrator calls each diagnose round: parse the
    latest capture into a card (None if nothing was captured)."""
    from .runtime_evidence import build_card, parse_capture

    def read() -> "str | None":
        return build_card(parse_capture(capture_path), target_label)

    return read


def extract_phase_text(trace: Trace) -> str:
    """The agent's final message in a phase = the last non-empty assistant text."""
    for s in reversed(trace.steps):
        if s.kind == StepKind.ASSISTANT_TEXT and (s.text or "").strip():
            return s.text
    return ""


def make_phase_runner(client, *, workdir, system_prompt, model, timeout_s, on_event,
                      cancel_event=None, temperature=None):
    """One opencode session per phase on the same workdir, tools scoped to the
    phase. Returns the phase trace + the agent's final text (the contract/plan).

    The EXACT prompt sent to the model is recorded as a leading PHASE_PROMPT step
    so the trace shows what entered the LLM context (the failure clusters, the
    contract, the runtime card, the graph-focus note, …) — not just the
    controller's one-line summary event. It carries no message_id and is excluded
    from agent metrics (see metrics.extract).

    cancel_event is forwarded to each phase's run_task so a UI cancel kills the
    IN-FLIGHT phase subprocess promptly (≤0.5s) — without it, a phased run ignores
    cancel until the whole run finishes."""
    def runner(phase: str, prompt: str, allowed_tools: list[str]) -> PhaseOutcome:
        res = client.run_task(
            workdir=str(workdir), system_prompt=system_prompt, model=model,
            user_message=prompt, timeout_s=timeout_s,
            agent_tools={t: True for t in allowed_tools}, on_event=on_event,
            cancel_event=cancel_event, temperature=temperature,
        )
        tr = res.trace
        # ts = the phase's earliest step so the prompt sorts to the phase start
        # (stitch sorts by ts, stable) — it precedes the agent's response.
        phase_ts = min((s.ts for s in tr.steps if s.ts is not None),
                       default=tr.started_at)
        tr.steps = [Step(kind=StepKind.PHASE_PROMPT, text=prompt, phase=phase,
                         ts=phase_ts)] + list(tr.steps)
        return PhaseOutcome(trace=tr, text=extract_phase_text(tr))

    return runner


def build_orchestrator_config(orch_cfg, mode: str) -> OrchestratorConfig:
    """OrchestratorConfig from the experiment's orchestration block + the
    condition's mode ('phased' | 'phased_plan' | ...)."""
    return OrchestratorConfig(
        target_label=orch_cfg.target_label,
        with_plan=(mode == "phased_plan"),
        max_diagnose_iters=orch_cfg.max_diagnose_iters,
        no_progress_limit=orch_cfg.no_progress_limit,
        cluster_cap=orch_cfg.cluster_cap,
    )
