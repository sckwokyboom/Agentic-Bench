# RapidCausalCoder — Phase 2 (experiment wiring) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `orchestration: rcc` a runnable bench condition end-to-end — config + runner wiring, the understand→implement prefix, review-mandated correctness fixes (full-suite-only best tracking, infra≠staleness), rcc telemetry in Trace/metrics, the UI option, A/B experiment YAML, and the memory hit-rate demo script.

**Architecture:** A thin prefix driver (`rcc_orchestrate.run_rcc_condition`) runs baseline→understand→implement→suite exactly like `phased` (same helpers), then either finishes green or seeds `run_rcc` with the accumulated trace state. The runner dispatches on `cond.orchestration == "rcc"`, degrading to plain phased when `.impact` coverage is unusable (mirroring `phased_graph`). Telemetry rides as new `Trace` dataclass fields → `metrics.extract` → UI.

**Tech Stack:** Python 3.11+, LangGraph (existing extra), pydantic (config), React/TS (one dropdown), pytest + vitest.

Spec: `docs/superpowers/specs/2026-07-08-rapidcausalcoder-mvp-design.md`.
Phase-1 review obligations (from the final review of commits 480e817..deedf12):
(a) `best_failed_reached`/`accepted_rounds` must not mix subset and full-suite counts;
(b) gradle `--continue` guaranteed on subset commands (holds by construction — the runner passes `suite_cmd` through `augment_for_full_run` before `make_subset_suite_runner`; documented at the Task 5 call site);
(c) degrade flags surfaced as Trace/metrics fields, not just event text;
(d) subset-runner INFRA failure during cache-fix must not count as staleness;
(e) subset "413 tests / 42 classes" blowup on putValue → class cap knob with an event.

---

## File Structure

- Modify: `abench/trace_model.py` — five additive `Trace` fields (`rcc_*`).
- Modify: `abench/rcc_subgraph.py` — `class_cap` + coverage-ranked `test_classes` + `classes_total`.
- Modify: `abench/rcc_graph.py` — review fixes, telemetry, subset/full counters, `RccSeed`.
- Create: `abench/rcc_orchestrate.py` — `run_rcc_condition` (prefix driver).
- Modify: `abench/config.py` — condition Literal += `"rcc"`; `OrchestrationCfg` rcc knobs.
- Modify: `abench/git_snapshot.py` — `strip_probe_lines_repo`.
- Modify: `abench/runner.py` — the `rcc` dispatch branch.
- Modify: `abench/metrics.py` — `rcc_*` keys in `extract()`.
- Modify: `web/src/components/OrchestrationSelect.tsx` — the `rcc` option.
- Create: `experiments/picocli-putValue/experiment-mac-rcc-ab.yaml` — the A/B config.
- Create: `scripts/rcc_hit_demo.py` — memory hit-rate demo (manual utility).
- Modify: `experiments/picocli-putValue/REPRODUCE.md` — rcc run + e2e smoke checklist.
- Tests: extend `tests/test_rcc_subgraph.py`, `tests/test_rcc_graph.py`, `tests/test_rcc_adapters.py`, `tests/test_git_snapshot.py`; create `tests/test_rcc_orchestrate.py`, `tests/test_rcc_config.py`.

DO NOT touch the unrelated uncommitted worktree changes (`web/src/components/SummaryTable.tsx`, `web/src/lib/exportTable.ts`, `web/tests/*`, `abench_ui/static/*`, `experiments/picocli-putValue/experiment-mac-*.yaml` untracked WIP files, `experiments/picocli-putValue/stripped-addrowvalues/`, `prompts/task-addrowvalues.md`). Do NOT run the web build (`npm run build`) — the committed `abench_ui/static` bundle must not absorb the user's WIP. Known pre-existing failing test on main (unrelated, do not fix): `tests/test_robustness.py::test_workdir_cleaned_up_when_client_raises`.

---

### Task 1: `Trace` rcc telemetry fields

**Files:**
- Modify: `abench/trace_model.py` (inside the `Trace` dataclass, right after `best_failed_reached`)
- Test: `tests/test_rcc_graph.py` (append)

- [ ] **Step 1: Write the failing test** — append to `tests/test_rcc_graph.py`:

```python
def test_trace_rcc_fields_roundtrip():
    from abench.trace_model import Trace, trace_from_dict
    tr = Trace()
    assert tr.rcc_root_rank is None and tr.rcc_memory_hit is False
    tr.rcc_root_rank = 1
    tr.rcc_memory_hit = True
    tr.rcc_beta_degraded = True
    tr.rcc_gamma_degraded = False
    tr.rcc_subset_test_runs = 2
    back = trace_from_dict(tr.to_dict())
    assert back.rcc_root_rank == 1 and back.rcc_memory_hit is True
    assert back.rcc_beta_degraded is True and back.rcc_gamma_degraded is False
    assert back.rcc_subset_test_runs == 2
```

- [ ] **Step 2: Run** `python3 -m pytest tests/test_rcc_graph.py::test_trace_rcc_fields_roundtrip -q` — FAIL (`Trace` has no attribute `rcc_root_rank` — dataclasses reject unknown attrs only on init; the assert on the default fails).

- [ ] **Step 3: Implement** — in `abench/trace_model.py`, directly after the `best_failed_reached: int | None = None` line, add:

```python
    # RapidCausalCoder (rcc) telemetry — None/False/0 for non-rcc runs.
    # root_rank: CausalRank position of the known true root (APFDc numerator);
    # memory_hit: the Memory Graph fast path was taken; *_degraded: the loop fell
    # back (beta = no runtime logs, gamma = no causal graph); subset_test_runs:
    # narrowed suite invocations (controller_test_runs counts subset + full).
    rcc_root_rank: int | None = None
    rcc_memory_hit: bool = False
    rcc_beta_degraded: bool = False
    rcc_gamma_degraded: bool = False
    rcc_subset_test_runs: int = 0
```

(`trace_from_dict` passes unknown keys straight into `Trace(**remaining)` — additive fields with defaults keep old trace.json files loadable.)

- [ ] **Step 4: Run** the test — PASS. Also `python3 -m pytest tests/test_report.py tests/test_rcc_graph.py -q` — all pass.

- [ ] **Step 5: Commit**

```bash
git add abench/trace_model.py tests/test_rcc_graph.py
git commit -m "feat(rcc): Trace telemetry fields (root_rank, memory_hit, degrades, subset runs)"
```

---

### Task 2: subgraph test-class ranking + cap

**Files:**
- Modify: `abench/rcc_subgraph.py`
- Test: `tests/test_rcc_subgraph.py` (append)

- [ ] **Step 1: Write the failing tests** — append to `tests/test_rcc_subgraph.py`:

```python
def test_class_cap_ranks_classes_by_method_coverage(tmp_path):
    cov = {
        "p.C.target": ["p.T1.a", "p.T2.b", "p.T3.c"],
        "p.C.n1":     ["p.T1.a", "p.T2.b"],           # T1,T2 cover 2 methods
        "p.C.n2":     ["p.T1.a"],                      # T1 covers 3 methods
    }
    impact = _write_impact(tmp_path, cov)
    sub = build_subgraph(impact, tmp_path, ["target"], class_cap=2)
    # T1 covers {target,n1,n2}=3 methods, T2 covers 2, T3 covers 1 -> cap keeps T1,T2
    assert sub.test_classes == ["p.T1", "p.T2"]
    assert sub.classes_total == 3
    # test_fqns narrowed to the kept classes
    assert sub.test_fqns == ["p.T1.a", "p.T2.b"]


def test_no_cap_keeps_all_classes_sorted_and_counts_total(tmp_path):
    impact = _write_impact(tmp_path, _COV)
    sub = build_subgraph(impact, tmp_path, ["putValue"])
    assert sub.classes_total == len(sub.test_classes)
```

- [ ] **Step 2: Run** `python3 -m pytest tests/test_rcc_subgraph.py -q` — the two new tests FAIL (`unexpected keyword argument 'class_cap'` / no attribute `classes_total`).

- [ ] **Step 3: Implement** — in `abench/rcc_subgraph.py`:

Add a field to the dataclass (after `sources`):

```python
    # How many distinct test classes the subgraph had BEFORE the class_cap was
    # applied (== len(test_classes) when uncapped). Dense targets like picocli's
    # putValue are covered by ~40 classes — the cap keeps subset runs cheap; the
    # graph reports the trim as a controller event.
    classes_total: int = 0
```

Replace the body of `build_subgraph` from the `tests = sorted(...)` line to the end with:

```python
    tests = sorted({t for m in methods for t in (coverage.get(m) or [])})

    def klass(test_fqn: str) -> str:
        return test_fqn.rsplit(".", 1)[0]

    # Rank classes by how many subgraph methods they exercise (descending, then
    # name) — when capped, keep the classes with the broadest subgraph coverage.
    per_class_methods: dict = {}
    for m in methods:
        for t in coverage.get(m) or []:
            per_class_methods.setdefault(klass(t), set()).add(m)
    ranked = sorted(per_class_methods, key=lambda c: (-len(per_class_methods[c]), c))
    classes_total = len(ranked)
    if class_cap is not None and class_cap > 0:
        ranked = ranked[:class_cap]
    kept = set(ranked)
    classes = sorted(kept)
    tests = [t for t in tests if klass(t) in kept]
    meta = _load(impact_dir / "methods.json") or {}
    sources = {m: read_span(workdir, meta[m], margin=margin, cap=cap)
               for m in methods if m in meta}
    return RccSubgraph(target_fqn=target, methods=methods, test_fqns=tests,
                       test_classes=classes, sources=sources,
                       classes_total=classes_total)
```

And extend the signature:

```python
def build_subgraph(impact_dir, workdir, target_methods, *, k: int = 5,
                   margin: int = 15, cap: int = 1200,
                   class_cap: "int | None" = None) -> "RccSubgraph | None":
```

- [ ] **Step 4: Run** `python3 -m pytest tests/test_rcc_subgraph.py -q` — 7 passed.

- [ ] **Step 5: Commit**

```bash
git add abench/rcc_subgraph.py tests/test_rcc_subgraph.py
git commit -m "feat(rcc): subset class cap — rank test classes by subgraph coverage"
```

---

### Task 3: rcc_graph review fixes + telemetry + seed

**Files:**
- Modify: `abench/rcc_graph.py`
- Test: `tests/test_rcc_graph.py` (append + two small edits)

- [ ] **Step 1: Write the failing tests** — append to `tests/test_rcc_graph.py`:

```python
def test_best_failed_tracks_full_suite_only():
    # initial full = 2 failed; fix-1 subset red with 1 failed must NOT lower best.
    phase = FakePhase()
    subset = [(_ev(1, 1), []), (_ev(1, 1), []), (_ev(1, 1), [])]
    full = []
    tr, _ = _run(phase, subset, full)
    assert tr.orchestration_outcome == "stuck"
    assert tr.best_failed_reached == 2          # full-suite semantics
    assert tr.accepted_rounds == 0              # no full-suite improvement


def test_cache_fix_infra_failure_keeps_entry():
    mem = FakeMemory({"p.C.put": {"causal_graph": json.loads(_GAMMA),
                                  "test_classes": ["p.CT"], "ts": 1.0}})
    phase = FakePhase()
    subset = [(_ev(0, 0, ran=False), []),        # cache-fix subset: INFRA failure
              (_ev(1, 1), ["RCC_PROBE x"]),      # beta
              (_ev(2, 0), [])]                   # fix-1 subset green
    full = [_ev(100, 0)]
    tr, _ = _run(phase, subset, full, memory=mem)
    assert tr.orchestration_outcome == "green"
    assert mem.invalidations == []               # infra is NOT staleness
    assert "infra" in "\n".join(_events(tr))


def test_rcc_telemetry_fields_on_green():
    phase = FakePhase()
    subset = [(_ev(1, 1), ["RCC_PROBE C.put: ret=null"]), (_ev(2, 0), [])]
    full = [_ev(100, 0)]
    tr, _ = _run(phase, subset, full)
    assert tr.rcc_root_rank == 1
    assert tr.rcc_memory_hit is False
    assert tr.rcc_beta_degraded is False
    assert tr.rcc_gamma_degraded is False
    assert tr.rcc_subset_test_runs == 2          # beta probe + fix-1 subset
    assert tr.controller_test_runs == 3          # + fix-1 full


def test_rcc_telemetry_flags_on_degrades():
    phase = FakePhase(gamma_texts=["garbage", "still garbage"])
    subset = [(_ev(0, 0, compiled=False, ran=False), []),
              (_ev(0, 0, compiled=False, ran=False), []),
              (_ev(2, 0), [])]
    full = [_ev(100, 0)]
    tr, _ = _run(phase, subset, full)
    assert tr.rcc_beta_degraded is True
    assert tr.rcc_gamma_degraded is True
    assert tr.rcc_root_rank is None              # no causal graph -> no rank


def test_memory_hit_sets_flag():
    mem = FakeMemory({"p.C.put": {"causal_graph": json.loads(_GAMMA),
                                  "test_classes": ["p.CT"], "ts": 1.0}})
    subset = [(_ev(2, 0), [])]
    full = [_ev(100, 0)]
    tr, _ = _run(FakePhase(), subset, full, memory=mem)
    assert tr.rcc_memory_hit is True


def test_seed_prefixes_trace_and_counters():
    from abench.rcc_graph import RccSeed
    from abench.trace_model import Step, StepKind
    pre = [Step(kind=StepKind.CONTROLLER, ts=1.0, turn=0,
                text="ran baseline test suite", phase="implement"),
           Step(kind=StepKind.CONTROLLER, ts=2.0, turn=0,
                text="implement done", phase="implement")]
    seed = RccSeed(phase_traces=[("implement", Trace())], ctrl=pre,
                   clock=2.0, full_runs=2, productive=1, best_failed=2)
    tr = run_rcc(
        RccConfig(target_label="p.C.put"), _SUB, initial=_ev(0, 2),
        phase_runner=FakePhase(),
        suite_runner=_seq_full([_ev(100, 0)]),
        subset_runner=_seq_subset([(_ev(1, 1), []), (_ev(2, 0), [])]),
        memory=FakeMemory(), strip_probes=lambda: 0, seed=seed,
    )
    ev = _events(tr)
    assert ev[0] == "ran baseline test suite"    # prefix events first (ts order)
    assert tr.controller_test_runs == 2 + 3      # seeded 2 + beta/fix subset/full
    assert tr.accepted_rounds == 1 + 1           # seeded 1 + green full
    assert tr.orchestration_outcome == "green"
```

Also EDIT two existing tests (semantics change — full-suite-only tracking):
- in `test_green_on_top1` nothing changes (asserts hold);
- no other existing assertion touches `best_failed_reached` — verify with `grep -n best_failed tests/test_rcc_graph.py` (only the new tests should match).

- [ ] **Step 2: Run** `python3 -m pytest tests/test_rcc_graph.py -q` — the 6 new tests FAIL (missing `RccSeed`, wrong best tracking, missing infra branch/fields).

- [ ] **Step 3: Implement in `abench/rcc_graph.py`:**

1. Add after the `RccConfig` dataclass:

```python
@dataclass
class RccSeed:
    """Accumulated state from the prefix driver (baseline→understand→implement)
    so the rcc loop stitches ONE continuous trace: prior phase traces + controller
    events, the clock to continue from, and the counters so far."""
    phase_traces: list
    ctrl: list
    clock: float
    full_runs: int
    productive: int
    best_failed: "int | None"
```

2. Change the signature:

```python
def run_rcc(cfg: RccConfig, sub: RccSubgraph, initial: SuiteEval, *,
            phase_runner, suite_runner, subset_runner, memory, strip_probes,
            on_event=None, cancel_event=None, seed: "RccSeed | None" = None) -> Trace:
```

3. Replace the counter initialisation:

```python
    clock = [seed.clock if seed else 0.0]
    full_runs = [seed.full_runs if seed else 0]
    subset_runs = [0]
    productive = [seed.productive if seed else 0]
```

(and rename every `test_runs[0]` use: `run_full` bumps `full_runs[0]`, `run_subset` bumps `subset_runs[0]`.)

4. In `memory_node`, seed `best_failed` and add state slots for telemetry:

```python
        return {"cached": entry, "attempt": 0, "cur": initial,
                "best_failed": (seed.best_failed if seed else
                                (initial.result.failed if initial.result.ran else None)),
                "specs": "", "probe_lines": [], "graph": None, "root_rank": None,
                "beta_degraded": False, "gamma_degraded": False,
                "ranks": [(m, 0.0) for m in sub.methods], "ctrl": steps}
```

and add to `RccState`: `root_rank: object`, `beta_degraded: bool`, `gamma_degraded: bool`.
Also make the miss/hit event report the subgraph size (cap visibility, obligation (e)):

```python
        steps.append(event(
            (f"memory: HIT for {sub.target_fqn} — trying the cached causal insight"
             if entry else
             f"memory: miss for {sub.target_fqn} — full causal pass")
            + f" (subgraph: {len(sub.methods)} methods, {len(sub.test_fqns)} tests, "
              f"{len(sub.test_classes)}/{sub.classes_total or len(sub.test_classes)} "
              "test classes)", "memory"))
```

5. `cache_fix_node` — full-suite-only tracking + infra≠staleness. Replace the section after `cur = ev` with:

```python
        full_ran = False
        if _green(ev):
            cur = run_full(steps, "cache-fix")
            full_ran = True
        infra = (not ev.result.ran) or (full_ran and not cur.result.ran)
        if _green(cur) and full_ran:
            steps.append(event("cache-fix: cached insight fixed it — subset + "
                               "full suite green", "cache-fix"))
        elif cancelled():
            steps.append(event("cache-fix: run cancelled — keeping the cached "
                               "entry (staleness was not tested)", "cache-fix"))
        elif infra:
            steps.append(event("cache-fix: subset/full run infra failure — "
                               "keeping the cached entry (staleness was not "
                               "tested); full causal pass", "cache-fix"))
        else:
            memory.invalidate(sub.target_fqn)
            steps.append(event("cache-fix: cached insight is STALE (tests still "
                               "red) — invalidated; full causal pass", "cache-fix"))
        bf = (_track_best(cur, state["best_failed"], productive)
              if full_ran else state["best_failed"])
        return {"cur": cur, "best_failed": bf,
                "phase_traces": [("cache-fix", f.trace)], "ctrl": steps}
```

6. `beta_node` — return the degrade flag: in the non-`beta_ok` branch add `"beta_degraded": True` to the returned dict (and `"beta_degraded": False` in the ok branch — replace the shared return with two explicit ones, or compute `degraded = not beta_ok` and return `{"probe_lines": lines, "beta_ok": beta_ok, "beta_degraded": (not beta_ok), ...}`).

7. `gamma_node` — record rank + degrade flag:

```python
        if graph is None:
            ranks = [(m, 0.0) for m in sub.methods]
            steps.append(event("gamma: still unparseable — degraded to "
                               "subgraph-order ranking (target first)", "gamma"))
            return {"graph": None, "ranks": ranks, "root_rank": None,
                    "gamma_degraded": True, "phase_traces": traces, "ctrl": steps}
        ranks = causal_rank(graph, sub.methods)
        rr = root_rank(ranks, sub.target_fqn)
        steps.append(event(
            f"gamma: causal graph with {len(graph.get('nodes', []))} nodes / "
            f"{len(graph.get('edges', []))} edges; CausalRank of target = "
            f"{rr}/{len(ranks)}", "gamma"))
        return {"graph": graph, "ranks": ranks, "root_rank": rr,
                "gamma_degraded": False, "phase_traces": traces, "ctrl": steps}
```

8. `fix_node` — full-suite-only tracking. Replace the trailing tracking line:

```python
        if _green(ev):
            ...run_full...
            bf = _track_best(cur, state["best_failed"], productive)
        else:
            ...red event...
            bf = state["best_failed"]        # subset counts never enter best
```

(i.e. move the `_track_best` call inside the green branch; the red branch passes the previous value through.)

9. After `stitch(...)` returns (`tr = stitch(...)` — introduce the local), set the telemetry before returning, in BOTH the normal and the fallback path:

```python
        tr.rcc_root_rank = final.get("root_rank")
        tr.rcc_memory_hit = bool(final.get("cached"))
        tr.rcc_beta_degraded = bool(final.get("beta_degraded"))
        tr.rcc_gamma_degraded = bool(final.get("gamma_degraded"))
        tr.rcc_subset_test_runs = subset_runs[0]
        return tr
```

and stitch's `controller_test_runs=full_runs[0] + subset_runs[0]` (sum — same "suite invocations" meaning the existing tests assert).

- [ ] **Step 4: Run** `python3 -m pytest tests/test_rcc_graph.py -q` — 17 passed (10 prior + 1 from Task 1 + 6 new).

- [ ] **Step 5: Full sweep** `python3 -m pytest tests/ -q -k "rcc"` — all pass.

- [ ] **Step 6: Commit**

```bash
git add abench/rcc_graph.py tests/test_rcc_graph.py
git commit -m "fix(rcc): full-suite-only best tracking, infra!=staleness, telemetry fields, RccSeed"
```

---

### Task 4: `rcc_orchestrate.py` — the prefix driver

**Files:**
- Create: `abench/rcc_orchestrate.py`
- Test: `tests/test_rcc_orchestrate.py`

- [ ] **Step 1: Write the failing tests:**

```python
# tests/test_rcc_orchestrate.py
import json

import pytest

pytest.importorskip("langgraph")

from abench.orchestrator import OrchestratorConfig, PhaseOutcome, SuiteEval
from abench.rcc_graph import RccConfig
from abench.rcc_orchestrate import run_rcc_condition
from abench.rcc_subgraph import RccSubgraph
from abench.regression_gate import SuiteResult
from abench.trace_model import StepKind, Trace

from tests.test_rcc_graph import (_GAMMA, _SUB, FakeMemory, FakePhase,
                                  _ev, _events, _seq_full, _seq_subset)

_OCFG = OrchestratorConfig(target_label="p.C.put", min_understand_reads=0)
_RCFG = RccConfig(target_label="p.C.put")

_CONTRACT = "The put method must return a non-null Cell and copy the value " \
            "into the table region honoring overflow."


class PrefixPhase(FakePhase):
    """understand returns a contract; alpha/gamma behave like FakePhase."""
    def __call__(self, phase, prompt, tools):
        out = super().__call__(phase, prompt, tools)
        if phase == "understand":
            return PhaseOutcome(trace=Trace(), text=_CONTRACT)
        return out


def _run_cond(subset, full, memory=None, phase=None):
    return run_rcc_condition(
        _OCFG, _RCFG, _SUB,
        phase_runner=phase or PrefixPhase(),
        suite_runner=_seq_full(full),
        subset_runner=_seq_subset(subset),
        memory=memory if memory is not None else FakeMemory(),
        strip_probes=lambda: 0,
    )


def test_green_on_implement_skips_rcc():
    phase = PrefixPhase()
    tr = run_rcc_condition(
        _OCFG, _RCFG, _SUB, phase_runner=phase,
        suite_runner=_seq_full([_ev(0, 2), _ev(100, 0)]),   # baseline red, implement green
        subset_runner=_seq_subset([]), memory=FakeMemory(), strip_probes=lambda: 0)
    assert tr.orchestration_outcome == "green"
    assert [c[0] for c in phase.calls] == ["understand", "implement"]
    ev = "\n".join(_events(tr))
    assert "rcc not invoked" in ev
    assert tr.controller_test_runs == 2


def test_red_implement_hands_off_to_rcc_with_seed():
    phase = PrefixPhase()
    tr = run_rcc_condition(
        _OCFG, _RCFG, _SUB, phase_runner=phase,
        # baseline red, implement still red, fix-1 full green
        suite_runner=_seq_full([_ev(0, 2), _ev(1, 1), _ev(100, 0)]),
        subset_runner=_seq_subset([(_ev(1, 1), ["RCC_PROBE x"]), (_ev(2, 0), [])]),
        memory=FakeMemory(), strip_probes=lambda: 0)
    assert tr.orchestration_outcome == "green"
    assert [c[0] for c in phase.calls] == ["understand", "implement", "alpha",
                                           "beta", "gamma", "fix-1"]
    ev = _events(tr)
    # one continuous trace: prefix events precede rcc events
    i_impl = next(i for i, t in enumerate(ev) if t.startswith("implement done"))
    i_mem = next(i for i, t in enumerate(ev) if t.startswith("memory:"))
    assert i_impl < i_mem
    assert tr.controller_test_runs == 2 + 3      # baseline+implement, beta+subset+full
    assert tr.rcc_root_rank == 1


def test_contract_fallback_still_reaches_rcc():
    phase = FakePhase()                           # understand returns "" -> fallback
    tr = run_rcc_condition(
        _OCFG, _RCFG, _SUB, phase_runner=phase,
        suite_runner=_seq_full([_ev(0, 2), _ev(1, 1), _ev(100, 0)]),
        subset_runner=_seq_subset([(_ev(1, 1), []), (_ev(2, 0), [])]),
        memory=FakeMemory(), strip_probes=lambda: 0)
    assert tr.orchestration_outcome == "green"
    assert "fallback" in "\n".join(_events(tr))
```

- [ ] **Step 2: Run** `python3 -m pytest tests/test_rcc_orchestrate.py -q` — FAIL (`ModuleNotFoundError: abench.rcc_orchestrate`).

- [ ] **Step 3: Implement `abench/rcc_orchestrate.py`:**

```python
"""The rcc condition driver: the SAME prefix as phased (baseline suite →
understand → implement → suite), then either finish green or hand the red state
to the rcc loop with an RccSeed so the stitched Trace is one continuous run.
Sequential code (no langgraph needed for a linear prefix); prompt/gate helpers
are single-sourced from orchestrator.py so the phased-vs-rcc A/B shares its
prefix verbatim."""
from __future__ import annotations

from .orchestrator import (
    _MAX_CONTRACT_CHARS,
    OrchestratorConfig,
    PhaseOutcome,
    SuiteEval,
    _cap,
    _track_best,
    contract_ok,
    fallback_contract,
    implement_prompt,
    understand_prompt,
)
from .rcc_graph import RccConfig, RccSeed, run_rcc
from .rcc_subgraph import RccSubgraph
from .regression_gate import SuiteResult
from .trace_model import Step, StepKind, Trace
from .trace_stitch import stitch


def run_rcc_condition(ocfg: OrchestratorConfig, rcfg: RccConfig,
                      sub: RccSubgraph, *, phase_runner, suite_runner,
                      subset_runner, memory, strip_probes,
                      on_event=None, cancel_event=None) -> Trace:
    phase_traces: list = []
    ctrl: list = []
    clock = [0.0]
    full_runs = [0]
    productive = [0]

    def emit(payload: dict) -> None:
        if on_event is not None:
            try:
                on_event(payload)
            except Exception:
                pass

    def event(text: str, phase: str) -> None:
        clock[0] += 1.0
        emit({"type": "controller", "phase": phase, "text": text})
        ctrl.append(Step(kind=StepKind.CONTROLLER, ts=clock[0], turn=0,
                         text=text, phase=phase))

    def cancelled() -> bool:
        return cancel_event is not None and cancel_event.is_set()

    def do_phase(name: str, prompt: str, tools: list) -> PhaseOutcome:
        if cancelled():
            event(f"run cancelled — skipping {name}", name)
            return PhaseOutcome(trace=Trace(), text="")
        emit({"type": "phase.start", "phase": name})
        emit({"type": "phase.prompt", "phase": name, "text": prompt})
        try:
            return phase_runner(name, prompt, tools)
        except Exception as exc:
            event(f"phase {name} FAILED ({exc}); continuing degraded", name)
            return PhaseOutcome(trace=Trace(), text="")

    def run_suite(phase: str) -> SuiteEval:
        full_runs[0] += 1
        try:
            return suite_runner()
        except Exception as exc:
            event(f"suite run FAILED ({exc})", phase)
            return SuiteEval(result=SuiteResult(compiled=True, ran=False,
                                                executed=0, passed=0, failed=0))

    # ── the phased-identical prefix ─────────────────────────────────────────
    base = run_suite("implement")
    best = base.result.failed if base.result.ran else None
    event(f"ran baseline test suite (stub, before any edits): "
          f"{base.result.passed} passed / {base.result.failed} failed", "implement")

    u = do_phase("understand", understand_prompt(ocfg), ["read", "grep"])
    ok, why = contract_ok(u, ocfg)
    contract = (_cap(u.text, _MAX_CONTRACT_CHARS) if ok
                else fallback_contract(base.failures, ocfg))
    event("agent's contract accepted (its spec of the method's required behaviour)"
          if ok else f"agent's contract rejected ({why}) — using an auto-derived fallback",
          "understand")
    phase_traces.append(("understand", u.trace))

    im = do_phase("implement", implement_prompt(ocfg, contract, ""), ["read", "edit"])
    cur = run_suite("implement")
    best = _track_best(cur, best, productive)
    event(f"implement done — {cur.result.passed} passed / {cur.result.failed} "
          f"failed (compiled={cur.result.compiled})", "implement")
    phase_traces.append(("implement", im.trace))

    green = cur.result.compiled and cur.result.ran and cur.result.failed == 0
    if green or cancelled():
        outcome = "cancelled" if cancelled() else "green"
        event(f"finalized: {outcome} — implement already green, rcc not invoked",
              "implement")
        tr = stitch(phase_traces, ctrl, outcome=outcome,
                    controller_test_runs=full_runs[0],
                    accepted_rounds=productive[0], reverted_rounds=0,
                    best_failed_reached=best)
        return tr

    # ── hand off the red state to the rcc loop (one continuous trace) ──────
    seed = RccSeed(phase_traces=phase_traces, ctrl=ctrl, clock=clock[0],
                   full_runs=full_runs[0], productive=productive[0],
                   best_failed=best)
    return run_rcc(rcfg, sub, cur, phase_runner=phase_runner,
                   suite_runner=suite_runner, subset_runner=subset_runner,
                   memory=memory, strip_probes=strip_probes,
                   on_event=on_event, cancel_event=cancel_event, seed=seed)
```

- [ ] **Step 4: Run** `python3 -m pytest tests/test_rcc_orchestrate.py tests/test_rcc_graph.py -q` — all pass. (If `_MAX_CONTRACT_CHARS` import fails, check the exact constant name in `abench/orchestrator.py` — `orchestrator_graph.py` imports it the same way.)

- [ ] **Step 5: Commit**

```bash
git add abench/rcc_orchestrate.py tests/test_rcc_orchestrate.py
git commit -m "feat(rcc): condition driver — phased-identical prefix, seeds the rcc loop"
```

---

### Task 5: config knobs + repo probe strip + runner dispatch

**Files:**
- Modify: `abench/config.py` (condition Literal + `OrchestrationCfg`)
- Modify: `abench/git_snapshot.py` (append)
- Modify: `abench/runner.py` (the orchestration branch)
- Test: `tests/test_rcc_config.py` (create), `tests/test_git_snapshot.py` (append)

- [ ] **Step 1: Failing tests.** Create `tests/test_rcc_config.py`:

```python
from abench.config import Condition, OrchestrationCfg


def test_condition_accepts_rcc():
    c = Condition(name="rcc", orchestration="rcc")
    assert c.orchestration == "rcc"


def test_orchestration_cfg_rcc_knobs_default():
    o = OrchestrationCfg()
    assert o.rcc_max_attempts == 2
    assert o.rcc_subgraph_k == 5
    assert o.rcc_subset_class_cap == 15
```

(If `Condition(name=..., orchestration=...)` needs more required fields, mirror how `tests/test_opencode_config_gating.py` constructs a Condition and adapt ONLY the constructor call.)

Append to `tests/test_git_snapshot.py`:

```python
def test_strip_probe_lines_repo(tmp_path):
    import subprocess
    from abench.git_snapshot import strip_probe_lines_repo
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    a = tmp_path / "A.java"
    a.write_text("class A {}\n")
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    subprocess.run(["git", "-c", "user.email=t@t", "-c", "user.name=t",
                    "commit", "-qm", "init"], cwd=tmp_path, check=True)
    # modified tracked file + new untracked file, each with a probe line
    a.write_text('class A { void m() { System.out.println("RCC_PROBE"); //[probe]\n } }\n')
    b = tmp_path / "B.java"
    b.write_text('class B {}\nSystem.out.println("x"); //[probe]\n')
    n = strip_probe_lines_repo(tmp_path)
    assert n == 2
    assert "//[probe]" not in a.read_text() and "//[probe]" not in b.read_text()
    assert strip_probe_lines_repo(tmp_path) == 0     # idempotent
```

- [ ] **Step 2: Run** both test files — FAIL (missing knobs / missing function).

- [ ] **Step 3: Implement.**

`abench/config.py` — extend the condition Literal (find the `orchestration: Literal[` field around line 63):

```python
    orchestration: Literal[
        "phased", "phased_plan", "phased_graph", "phased_runtime", "rcc"
    ] | None = Field(
```

and extend its description with one sentence: `"'rcc' = RapidCausalCoder: the same understand→implement prefix, then a causal-debugging loop (Alpha/Beta/Gamma + CausalRank + Memory Graph) instead of plain diagnose."`

`OrchestrationCfg` — append fields:

```python
    rcc_max_attempts: int = Field(
        default=2, title="rcc fix attempts",
        description="Fix ladder depth for 'rcc': top-1 → … → DEFER.")
    rcc_subgraph_k: int = Field(
        default=5, title="rcc subgraph neighbors",
        description="Neighbors kept around the target in the mutational subgraph.")
    rcc_subset_class_cap: int = Field(
        default=15, title="rcc subset class cap",
        description=(
            "Max test CLASSES in the narrowed subset run (ranked by how many "
            "subgraph methods each class covers). Dense targets are covered by "
            "40+ classes — uncapped subsets erase the cycle-time win. The full "
            "suite still gates every accept; 0/None disables the cap."))
```

`abench/git_snapshot.py` — append:

```python
def strip_probe_lines_repo(repo: Path, marker: str = "//[probe]") -> int:
    """Strip marked probe lines from EVERY changed .java file (tracked or
    untracked) — the rcc loop's mid-run cleanup after the instrumented subset
    run. Per-file work is strip_marked_lines. Returns total lines removed;
    best-effort (a git failure returns 0 rather than aborting the run)."""
    try:
        out = _git(repo, "status", "--porcelain")
    except Exception:
        return 0
    total = 0
    for ln in out.splitlines():
        if not ln.strip():
            continue
        path = ln[3:].strip()
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        if path.endswith(".java"):
            total += strip_marked_lines(repo, path, marker=marker)
    return total
```

`abench/runner.py` — inside the orchestration branch (the block starting `if cond.orchestration and exp.orchestration is not None:`), immediately AFTER the `_orch_event` definition and BEFORE the `in_blast_radius = None` line, insert the dispatch, and indent the existing `in_blast_radius`/`read_evidence`/`trace = _orchestrate(...)` code under the `else:`:

```python
                    if cond.orchestration == "rcc":
                        # RapidCausalCoder: phased-identical prefix, then the
                        # causal-debugging loop. Degrades to plain phased when
                        # the .impact coverage is unusable (mirrors phased_graph).
                        from .git_snapshot import strip_probe_lines_repo
                        from .orchestration_adapters import make_subset_suite_runner
                        from .rcc_graph import RccConfig
                        from .rcc_memory import RccMemory
                        from .rcc_orchestrate import run_rcc_condition
                        from .rcc_subgraph import build_subgraph
                        ocfg = exp.orchestration
                        sub = build_subgraph(
                            workdir / ".impact", workdir, exp.target_methods or [],
                            k=ocfg.rcc_subgraph_k,
                            class_cap=ocfg.rcc_subset_class_cap or None)
                        if sub is None:
                            _log("[abench] rcc: no usable .impact coverage for the "
                                 "targets — degrading to plain phased")
                            trace = _orchestrate(
                                build_orchestrator_config(exp.orchestration, "phased"),
                                phase_runner=phase_runner, suite_runner=suite_runner,
                                snapshot=lambda: _gsnap(workdir),
                                restore=lambda t: _grestore(workdir, t),
                                on_event=_orch_event, in_blast_radius=None,
                                read_evidence=None, cancel_event=cancel_event)
                        else:
                            # ABENCH_RCC_MEMORY: persistent path for the hit-rate
                            # demo; default = per-rep file (rep independence in A/B).
                            mem_path = (os.environ.get("ABENCH_RCC_MEMORY")
                                        or str(rundir / "rcc-memory.json"))
                            _log(f"[abench] rcc: subgraph {len(sub.methods)} methods, "
                                 f"{len(sub.test_classes)}/{sub.classes_total} test "
                                 f"classes; memory at {mem_path}")
                            trace = run_rcc_condition(
                                build_orchestrator_config(exp.orchestration, "phased"),
                                RccConfig(target_label=ocfg.target_label,
                                          max_attempts=ocfg.rcc_max_attempts,
                                          cluster_cap=ocfg.cluster_cap),
                                sub,
                                phase_runner=phase_runner,
                                suite_runner=suite_runner,
                                subset_runner=make_subset_suite_runner(
                                    workdir, suite_cmd, exp.verify.timeout_s),
                                memory=RccMemory(mem_path),
                                strip_probes=lambda: strip_probe_lines_repo(workdir),
                                on_event=_orch_event, cancel_event=cancel_event)
                        result = RunResult(trace=trace)
                    else:
                        <existing in_blast_radius = None … result = RunResult(trace=trace) block, re-indented one level>
```

Notes for the implementer: `suite_cmd` is already `augment_for_full_run(...)`-processed → carries `--continue` (obligation (b)); `rundir` is defined earlier in the function (`rundir = root / cond.name / f"rep_{rep}"`); keep the existing `else:` body byte-identical apart from indentation.

- [ ] **Step 4: Run** `python3 -m pytest tests/test_rcc_config.py tests/test_git_snapshot.py tests/test_runner_orchestration_select.py tests/test_bench_run_dispatch.py -q` — all pass. Then `python3 -m pytest tests/ -q -k "runner or config"` — pass.

- [ ] **Step 5: Commit**

```bash
git add abench/config.py abench/git_snapshot.py abench/runner.py tests/test_rcc_config.py tests/test_git_snapshot.py
git commit -m "feat(rcc): condition wiring — config knobs, repo probe strip, runner dispatch"
```

---

### Task 6: metrics additions

**Files:**
- Modify: `abench/metrics.py` (the `extract()` return dict)
- Test: `tests/test_metrics.py` if it exists, else append to `tests/test_rcc_graph.py`

- [ ] **Step 1: Failing test** (append to `tests/test_rcc_graph.py`; reuse `_M` pattern from `tests/test_orchestrator_graph_parity.py`):

```python
def test_metrics_carry_rcc_fields():
    from abench.metrics import MetricsConfig, extract
    from abench.trace_model import Trace
    m_cfg = MetricsConfig(test_command_patterns=[], shell_tool_names=[],
                          read_tool_names=[], search_tool_names=[],
                          command_arg_keys=[])
    tr = Trace()
    tr.rcc_root_rank = 2
    tr.rcc_memory_hit = True
    tr.rcc_beta_degraded = True
    tr.rcc_gamma_degraded = False
    tr.rcc_subset_test_runs = 4
    m = extract(tr, "", m_cfg)
    assert m["rcc_root_rank"] == 2 and m["rcc_memory_hit"] is True
    assert m["rcc_beta_degraded"] is True and m["rcc_gamma_degraded"] is False
    assert m["rcc_subset_test_runs"] == 4
```

(If `MetricsConfig` requires more/other kwargs, copy the exact `_M` construction from `tests/test_orchestrator_graph_parity.py:17`.)

- [ ] **Step 2: Run** — FAIL (`KeyError: 'rcc_root_rank'`).

- [ ] **Step 3: Implement** — in `abench/metrics.py`, inside the literal dict `extract()` returns (after the `"verify_insensitive": trace.verify_insensitive,` line), add:

```python
        # RapidCausalCoder telemetry (None/False/0 for non-rcc runs) — feeds
        # APFDc (root_rank), the hit-rate demo, and degrade-frequency analysis.
        "rcc_root_rank": trace.rcc_root_rank,
        "rcc_memory_hit": trace.rcc_memory_hit,
        "rcc_beta_degraded": trace.rcc_beta_degraded,
        "rcc_gamma_degraded": trace.rcc_gamma_degraded,
        "rcc_subset_test_runs": trace.rcc_subset_test_runs,
```

- [ ] **Step 4: Run** the test + `python3 -m pytest tests/ -q -k "metric or report"` — pass.

- [ ] **Step 5: Commit**

```bash
git add abench/metrics.py tests/test_rcc_graph.py
git commit -m "feat(rcc): rcc telemetry in metrics.extract"
```

---

### Task 7: UI option

**Files:**
- Modify: `web/src/components/OrchestrationSelect.tsx`

- [ ] **Step 1: Edit** — extend the type and OPTIONS:

```tsx
type Mode = "phased" | "phased_plan" | "phased_graph" | "phased_runtime" | "rcc" | null;

const OPTIONS: { value: string; label: string }[] = [
  { value: "", label: "Autonomous (none)" },
  { value: "phased", label: "Phased" },
  { value: "phased_plan", label: "Phased + plan" },
  { value: "phased_graph", label: "Phased + graph focus" },
  { value: "phased_runtime", label: "Phased + runtime evidence" },
  { value: "rcc", label: "RapidCausalCoder (rcc)" },
];
```

- [ ] **Step 2: Verify** — `cd web && npx vitest run 2>&1 | tail -5` — the existing suite passes (there may be pre-existing failures from the user's WIP on SummaryTable/exportTable — compare with `git stash`-free judgment: only ensure YOUR change introduces no NEW failures; if unsure, run `npx tsc --noEmit` and confirm no errors mention OrchestrationSelect). Do NOT run `npm run build`.

- [ ] **Step 3: Commit**

```bash
git add web/src/components/OrchestrationSelect.tsx
git commit -m "feat(rcc): orchestration mode option in the experiment form"
```

---

### Task 8: A/B experiment YAML + hit-rate demo script

**Files:**
- Create: `experiments/picocli-putValue/experiment-mac-rcc-ab.yaml`
- Create: `scripts/rcc_hit_demo.py`

- [ ] **Step 1: Create the YAML** (modeled on `experiment-mac.yaml`; the overlay ships `.impact` data into the workdir — same overlay the graph/tool arms use):

```yaml
# phased-vs-rcc A/B on the putValue mutant (host mode, Mac). Same model, same
# temperature, same understand->implement prefix — the ONLY contrast is the
# repair loop: plain diagnose (phased) vs RapidCausalCoder (rcc).
#
# Run (venv active, JDK 21):
#   JAVA_HOME=/opt/homebrew/opt/openjdk@21 \
#     .venv/bin/abench run experiments/picocli-putValue/experiment-mac-rcc-ab.yaml
#
# Memory validity: each rep gets a FRESH rcc-memory.json (per-rep rundir).
# The hit-rate demo is scripts/rcc_hit_demo.py — NEVER mixed into this A/B.
name: picocli-putValue-rcc-ab
fixture_path: ./stripped
reference_path: ./original
task_prompt: ./prompts/task.md
system_prompt: ./prompts/system.md

model: openrouter/nvidia/nemotron-3-super-120b-a12b:free
timeout_s: 1800
repetitions: 1      # raise to 3+ for the real A/B; 1 = smoke
output_dir: ./runs

opencode:
  agent: abench
  sandbox:
    mode: none

orchestration:
  target_label: the TextTable.putValue method
  max_diagnose_iters: 8
  no_progress_limit: 2
  cluster_cap: 5
  rcc_max_attempts: 2
  rcc_subgraph_k: 5
  rcc_subset_class_cap: 15

conditions:
  - name: phased
    orchestration: phased
    overlay: ./overlays/impact-artifacts
    restore_non_target_before_verify: true
  - name: rcc
    orchestration: rcc
    overlay: ./overlays/impact-artifacts
    restore_non_target_before_verify: true

target_file: src/main/java/picocli/CommandLine.java
target_methods: [putValue]

verify:
  timeout_s: 1800

metrics:
  test_command_patterns:
    - "(mvn|mvnw)( |$)"
    - "gradle(w)?( |$)"
```

Validate it loads: `python3 -c "from abench.config import load_experiment; e = load_experiment('experiments/picocli-putValue/experiment-mac-rcc-ab.yaml'); print(e.conditions[1].orchestration)"` → `rcc`. (If the loader function has a different name, find it with `grep -n "def load" abench/config.py` and use that; if `restore_non_target_before_verify` or `overlay` are named differently on Condition, check `grep -n "restore_non_target\|overlay" abench/config.py` and adjust the YAML keys.)

- [ ] **Step 2: Create `scripts/rcc_hit_demo.py`** (manual utility for the prepared machine — no unit tests; validated by `--help` and the e2e checklist):

```python
#!/usr/bin/env python3
"""Memory Graph hit-rate demo: run the SAME rcc condition twice against ONE
persistent memory file and report hit rate + wall-time delta. Deliberately
separate from the A/B (which resets memory per rep) — this measures learning
across encounters, not condition contrast.

Usage (venv active, JDK 21, prepared picocli machine):
    python3 scripts/rcc_hit_demo.py experiments/picocli-putValue/experiment-mac-rcc-ab.yaml
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


def newest_rcc_trace(exp_dir: Path, name: str) -> dict:
    root = exp_dir / "runs" / name
    batches = sorted((d for d in root.iterdir() if d.is_dir()), key=lambda d: d.name)
    trace = batches[-1] / "rcc" / "rep_1" / "trace.json"
    return json.loads(trace.read_text())


def summarize(trace: dict) -> dict:
    wall = None
    if trace.get("started_at") and trace.get("ended_at"):
        wall = trace["ended_at"] - trace["started_at"]
    return {"memory_hit": bool(trace.get("rcc_memory_hit")),
            "outcome": trace.get("orchestration_outcome"),
            "wall_s": wall,
            "suite_runs": trace.get("controller_test_runs"),
            "subset_runs": trace.get("rcc_subset_test_runs")}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("experiment", help="experiment YAML with an 'rcc' condition")
    ap.add_argument("--memory", default=None,
                    help="persistent memory path (default: a temp file)")
    args = ap.parse_args()
    exp = Path(args.experiment).resolve()
    mem = args.memory or str(Path(tempfile.mkdtemp(prefix="rcc-mem-")) / "memory.json")
    env = dict(os.environ, ABENCH_RCC_MEMORY=mem)
    name = None
    runs = []
    for i in (1, 2):
        print(f"[hit-demo] run {i}/2 (memory: {mem}) …", flush=True)
        subprocess.run([sys.executable, "-m", "abench.cli", "run", str(exp)],
                       env=env, check=True)
        if name is None:
            import yaml
            name = yaml.safe_load(exp.read_text())["name"]
        runs.append(summarize(newest_rcc_trace(exp.parent, name)))
    r1, r2 = runs
    print(json.dumps({"run1": r1, "run2": r2}, indent=2))
    print(f"[hit-demo] hit rate on repeat: {1.0 if r2['memory_hit'] else 0.0}")
    if r1["wall_s"] and r2["wall_s"]:
        print(f"[hit-demo] cycle-time reduction: "
              f"{(1 - r2['wall_s'] / r1['wall_s']) * 100:.0f}%")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

Verify: `python3 scripts/rcc_hit_demo.py --help` prints usage. (If the CLI entry is not `python3 -m abench.cli run <yaml>`, check `grep -n "console_scripts\|\[project.scripts\]" -A 3 pyproject.toml` and use the installed `abench run` binary instead.)

- [ ] **Step 3: Commit**

```bash
git add experiments/picocli-putValue/experiment-mac-rcc-ab.yaml scripts/rcc_hit_demo.py
git commit -m "feat(rcc): phased-vs-rcc A/B config + memory hit-rate demo script"
```

---

### Task 9: docs + final sweep

**Files:**
- Modify: `experiments/picocli-putValue/REPRODUCE.md` (append)

- [ ] **Step 1: Append to `experiments/picocli-putValue/REPRODUCE.md`:**

```markdown
## RapidCausalCoder (rcc) — A/B + e2e smoke

Prereqs on the prepared machine: venv with `pip install -e '.[langgraph]'`,
JDK 21 as JAVA_HOME, the fixture prepared (`./stripped`), `.impact` shipped by
the `overlays/impact-artifacts` overlay.

A/B (phased vs rcc; fresh memory per rep — rep-independent):

    JAVA_HOME=/opt/homebrew/opt/openjdk@21 \
      .venv/bin/abench run experiments/picocli-putValue/experiment-mac-rcc-ab.yaml

E2E smoke checklist (1 rep, rcc condition, TraceView):
- phase bands appear in order: understand → implement → memory → alpha → beta →
  gamma → fix-1 [→ fix-2];
- the beta phase turns show `RCC_PROBE …` println insertions with `//[probe]`;
- the FINAL diff contains NO `//[probe]` lines (in-loop strip + the
  restore_non_target_before_verify belt);
- metrics carry `rcc_root_rank` (expect 1 on putValue when gamma parsed),
  `rcc_subset_test_runs` > 0, degrade flags false (or true WITH matching
  controller events);
- the subgraph event reports the class cap: "… 15/42 test classes".

Memory hit-rate demo (separate from the A/B by design):

    python3 scripts/rcc_hit_demo.py \
      experiments/picocli-putValue/experiment-mac-rcc-ab.yaml
```

- [ ] **Step 2: Full test sweep** — `python3 -m pytest tests/ -q`: everything passes except the known pre-existing `tests/test_robustness.py::test_workdir_cleaned_up_when_client_raises`.

- [ ] **Step 3: Commit**

```bash
git add experiments/picocli-putValue/REPRODUCE.md
git commit -m "docs(rcc): A/B run + e2e smoke checklist + hit-demo usage"
```

---

## Deviations to flag during execution

- Runner insertion anchors: the orchestration branch currently sits at `abench/runner.py:541-620`; if line numbers drifted, anchor on the literal strings `_orch_event` and `in_blast_radius = None`.
- If `Condition`/`load_experiment`/`MetricsConfig` constructor details differ, the task steps name the exact greps/tests to copy from — adapt the CALL, never the production code's semantics.
- `python3 -m abench.cli` vs the `abench` entrypoint: check `pyproject.toml [project.scripts]`.

## Out of scope

The real A/B run and the e2e smoke themselves (prepared machine, user-driven); addRowValues A/B YAML (clone of Task 8's file with `target_methods: [addRowValues]`, `fixture_path: ./stripped-addrowvalues`, `task_prompt: ./prompts/task-addrowvalues.md` — the user's untracked WIP files cover this); escalation/k-medoid/semantic memory (Phase 3 per spec); the canvas graph overlay (parked editor project).
