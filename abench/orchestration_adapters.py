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

import shutil
import subprocess
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Callable

from .failure_report import parse_junit_dir
from .orchestrator import OrchestratorConfig, PhaseOutcome, SuiteEval
from .regression_gate import SuiteResult
from .trace_model import StepKind, Trace

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


def make_suite_runner(workdir: Path, command: str, timeout_s: int) -> Callable[[], SuiteEval]:
    """Host subprocess (like verify) + JUnit XML breakdown. Clears stale results
    first so each call reflects only its own run."""
    workdir = Path(workdir)

    def runner() -> SuiteEval:
        _clear_results(workdir)
        try:
            proc = subprocess.run(command, shell=True, cwd=workdir,
                                  capture_output=True, text=True, timeout=timeout_s)
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


def extract_phase_text(trace: Trace) -> str:
    """The agent's final message in a phase = the last non-empty assistant text."""
    for s in reversed(trace.steps):
        if s.kind == StepKind.ASSISTANT_TEXT and (s.text or "").strip():
            return s.text
    return ""


def make_phase_runner(client, *, workdir, system_prompt, model, timeout_s, on_event):
    """One opencode session per phase on the same workdir, tools scoped to the
    phase. Returns the phase trace + the agent's final text (the contract/plan)."""
    def runner(phase: str, prompt: str, allowed_tools: list[str]) -> PhaseOutcome:
        res = client.run_task(
            workdir=str(workdir), system_prompt=system_prompt, model=model,
            user_message=prompt, timeout_s=timeout_s,
            agent_tools={t: True for t in allowed_tools}, on_event=on_event,
        )
        return PhaseOutcome(trace=res.trace, text=extract_phase_text(res.trace))

    return runner


def build_orchestrator_config(orch_cfg, mode: str) -> OrchestratorConfig:
    """OrchestratorConfig from the experiment's orchestration block + the
    condition's mode ('phased' | 'phased_plan')."""
    return OrchestratorConfig(
        contract_fields=list(orch_cfg.contract_fields),
        target_label=orch_cfg.target_label,
        with_plan=(mode == "phased_plan"),
        max_diagnose_iters=orch_cfg.max_diagnose_iters,
        no_progress_limit=orch_cfg.no_progress_limit,
        cluster_cap=orch_cfg.cluster_cap,
    )
