# tests/test_rcc_graph.py
import json

import pytest

pytest.importorskip("langgraph")   # optional extra — skip cleanly without it

from abench.orchestrator import PhaseOutcome, SuiteEval
from abench.rcc_graph import RccConfig, run_rcc
from abench.rcc_graph_layers import (
    annotate_status, build_index, build_subgraph, render_prompt_slice,
)
from abench.rcc_mutation_graph import MgEdge, MgVertex, MutationGraph
from abench.regression_gate import SuiteResult
from abench.trace_model import StepKind, Trace

# _SUB stays a MutationGraph — run_rcc_condition (tested in
# tests/test_rcc_orchestrate.py, which imports it from here) still takes the
# raw graph and builds the R2 layers itself. run_rcc (tested below) now takes
# the v2 PromptSlice + focused-method fqn list the layers produce, so
# _SLICE/_METHODS are built once, here, via the real layer functions to stay
# faithful.
_SUB = MutationGraph(
    target_id="method:p.C.put",
    vertices=[MgVertex(id="method:p.C.put", type="method", fqn="p.C.put",
                       is_changed=True, source="Cell put(){ return null; }"),
              MgVertex(id="method:p.C.get", type="method", fqn="p.C.get",
                       source="Object get(){...}"),
              MgVertex(id="test:p.CT.t1", type="test", fqn="p.CT.t1"),
              MgVertex(id="test:p.CT.t2", type="test", fqn="p.CT.t2")],
    edges=[MgEdge(src="method:p.C.put", tgt="method:p.C.get", type="CALLS"),
           MgEdge(src="test:p.CT.t1", tgt="method:p.C.put", type="TEST_ASSERTS"),
           MgEdge(src="test:p.CT.t2", tgt="method:p.C.put", type="TEST_ASSERTS")],
)


def _build_slice(failed_ids):
    g = annotate_status(_SUB, failed_ids=set(failed_ids))
    idx = build_index(g)
    subgraph = build_subgraph(g, failed_ids=set(failed_ids))
    ps = render_prompt_slice(g, subgraph, idx)
    methods = [m["fqn"] for m in subgraph["focused_methods"]] or subgraph["methods"]
    return ps, methods


_SLICE, _METHODS = _build_slice({"p.CT.t1", "p.CT.t2"})

_GAMMA = json.dumps({
    "vertices": [{"id": "cd1", "mutation_vertex": "method:p.C.put",
                  "type": "root_cause", "is_root_cause": True, "confidence": 0.95,
                  "violated": True, "runtime_value": "ret=null"},
                 {"id": "cd2", "mutation_vertex": "method:p.C.get",
                  "type": "downstream_effect", "is_root_cause": False,
                  "confidence": 0.9, "violated": True}],
    "edges": [{"from": "cd1", "to": "cd2", "type": "CAUSES",
               "path": ["method:p.C.put", "method:p.C.get"], "reasoning": "null propagates"}],
})


def _ev(passed, failed, compiled=True, ran=True):
    return SuiteEval(result=SuiteResult(compiled=compiled, ran=ran,
                                        executed=passed + failed,
                                        passed=passed, failed=failed))


class FakePhase:
    """phase_runner fake: records calls; canned text per phase kind."""
    def __init__(self, gamma_texts=(_GAMMA,), alpha_text="specs: put returns non-null"):
        self.calls = []
        self.gamma_texts = list(gamma_texts)
        self.alpha_text = alpha_text

    def __call__(self, phase, prompt, tools):
        self.calls.append((phase, prompt, tuple(tools)))
        text = ""
        if phase == "alpha":
            text = self.alpha_text
        elif phase.startswith("gamma"):
            text = self.gamma_texts.pop(0) if self.gamma_texts else ""
        return PhaseOutcome(trace=Trace(), text=text)


def _seq_subset(evals_and_lines):
    it = iter(evals_and_lines)

    def run(test_classes):
        return next(it)
    return run


def _seq_full(evals):
    it = iter(evals)

    def run():
        return next(it)
    return run


class FakeMemory:
    def __init__(self, entries=None):
        self.entries = dict(entries or {})
        self.puts, self.invalidations = [], []

    def get(self, fqn):
        return self.entries.get(fqn)

    def put(self, fqn, causal_graph, test_classes):
        self.puts.append(fqn)
        self.entries[fqn] = {"causal_graph": causal_graph,
                             "test_classes": list(test_classes), "ts": 1.0}

    def invalidate(self, fqn):
        self.invalidations.append(fqn)
        self.entries.pop(fqn, None)


def _events(trace):
    return [s.text for s in trace.steps if s.kind == StepKind.CONTROLLER]


def _phases_called(fake):
    return [c[0] for c in fake.calls]


def _run(phase, subset_seq, full_seq, memory=None, cfg=None, strip=None):
    strips = []
    tr = run_rcc(
        cfg or RccConfig(target_label="p.C.put"), _SLICE, _METHODS, initial=_ev(0, 2),
        phase_runner=phase,
        suite_runner=_seq_full(full_seq),
        subset_runner=_seq_subset(subset_seq),
        memory=memory if memory is not None else FakeMemory(),
        strip_probes=strip or (lambda: strips.append(1) or 3),
    )
    return tr, strips


def test_green_on_top1():
    phase = FakePhase()
    # subset calls: beta probe run (red, with logs), fix-1 subset (green)
    subset = [(_ev(1, 1), ["RCC_PROBE C.put: ret=null"]), (_ev(2, 0), [])]
    full = [_ev(100, 0)]                       # fix-1 full suite
    mem = FakeMemory()
    tr, strips = _run(phase, subset, full, memory=mem)
    assert tr.orchestration_outcome == "green"
    assert _phases_called(phase) == ["alpha", "beta", "gamma", "fix-1"]
    assert mem.puts == ["p.C.put"]
    assert strips == [1]                       # probes stripped exactly once
    ev = "\n".join(_events(tr))
    assert "CausalRank of target = 1/2" in ev
    assert "memory: miss" in ev
    assert tr.controller_test_runs == 3   # beta probe + fix-1 subset + fix-1 full


def test_top2_rescue():
    phase = FakePhase()
    subset = [(_ev(1, 1), ["RCC_PROBE x"]),    # beta probe run
              (_ev(1, 1), []),                 # fix-1 subset red
              (_ev(2, 0), [])]                 # fix-2 subset green
    full = [_ev(100, 0)]                       # fix-2 full
    tr, _ = _run(phase, subset, full)
    assert tr.orchestration_outcome == "green"
    assert _phases_called(phase) == ["alpha", "beta", "gamma", "fix-1", "fix-2"]


def test_defer_after_max_attempts():
    phase = FakePhase()
    subset = [(_ev(1, 1), []), (_ev(1, 1), []), (_ev(1, 1), [])]
    full = []                                  # full suite never reached
    mem = FakeMemory()
    tr, _ = _run(phase, subset, full, memory=mem)
    assert tr.orchestration_outcome == "stuck"
    assert mem.puts == []                      # nothing saved on DEFER
    assert "finalized: stuck" in "\n".join(_events(tr))
    assert tr.controller_test_runs == 3   # beta probe + 2 red fix subsets; full never ran


def test_full_suite_red_consumes_attempt():
    phase = FakePhase()
    subset = [(_ev(1, 1), []),                 # beta
              (_ev(2, 0), []),                 # fix-1 subset green
              (_ev(2, 0), [])]                 # fix-2 subset green
    full = [_ev(90, 10), _ev(100, 0)]          # fix-1 full red -> fix-2 full green
    tr, _ = _run(phase, subset, full)
    assert tr.orchestration_outcome == "green"
    assert _phases_called(phase)[-2:] == ["fix-1", "fix-2"]


def test_memory_hit_fast_path_skips_analysis():
    mem = FakeMemory({"p.C.put": {"causal_graph": json.loads(_GAMMA),
                                  "test_classes": ["p.CT"], "ts": 1.0}})
    phase = FakePhase()
    subset = [(_ev(2, 0), [])]                 # cache-fix subset green
    full = [_ev(100, 0)]                       # cache-fix full green
    tr, _ = _run(phase, subset, full, memory=mem)
    assert tr.orchestration_outcome == "green"
    assert _phases_called(phase) == ["cache-fix"]        # NO alpha/beta/gamma
    assert mem.invalidations == []
    assert "memory: HIT" in "\n".join(_events(tr))
    # the graph is (re)saved on success
    assert mem.puts == ["p.C.put"]


def test_cancel_during_cache_fix_keeps_the_entry():
    class _Cancel:
        def is_set(self):
            return True

    mem = FakeMemory({"p.C.put": {"causal_graph": json.loads(_GAMMA),
                                  "test_classes": ["p.CT"], "ts": 1.0}})
    tr = run_rcc(
        RccConfig(target_label="p.C.put"), _SLICE, _METHODS, initial=_ev(0, 2),
        phase_runner=FakePhase(),
        suite_runner=_seq_full([]),
        subset_runner=_seq_subset([(_ev(1, 1), [])]),
        memory=mem, strip_probes=lambda: 0, cancel_event=_Cancel(),
    )
    assert tr.orchestration_outcome == "cancelled"
    assert mem.invalidations == []             # cancel is not staleness


def test_stale_cache_invalidates_then_full_pass_succeeds():
    mem = FakeMemory({"p.C.put": {"causal_graph": json.loads(_GAMMA),
                                  "test_classes": ["p.CT"], "ts": 1.0}})
    phase = FakePhase()
    subset = [(_ev(1, 1), []),                 # cache-fix subset red -> stale
              (_ev(1, 1), ["RCC_PROBE x"]),    # beta probe run
              (_ev(2, 0), [])]                 # fix-1 subset green
    full = [_ev(100, 0)]                       # fix-1 full green
    tr, _ = _run(phase, subset, full, memory=mem)
    assert tr.orchestration_outcome == "green"
    assert mem.invalidations == ["p.C.put"]
    assert _phases_called(phase) == ["cache-fix", "alpha", "beta", "gamma",
                                     "fix-1"]
    assert "STALE" in "\n".join(_events(tr))


def test_beta_compile_break_degrades_to_no_logs():
    phase = FakePhase()
    subset = [(_ev(0, 0, compiled=False, ran=False), []),   # beta broke build
              (_ev(0, 0, compiled=False, ran=False), []),   # repair also broke
              (_ev(2, 0), [])]                              # fix-1 subset green
    full = [_ev(100, 0)]
    tr, strips = _run(phase, subset, full)
    assert tr.orchestration_outcome == "green"
    assert _phases_called(phase) == ["alpha", "beta", "beta-repair", "gamma",
                                     "fix-1"]
    ev = "\n".join(_events(tr))
    assert "NO-LOGS" in ev
    assert strips == [1]                       # probes still stripped
    # gamma got the no-logs marker in its prompt
    gamma_prompt_text = [p for (n, p, _t) in phase.calls if n == "gamma"][0]
    assert "no runtime logs" in gamma_prompt_text


def test_gamma_unparseable_twice_falls_back_to_target_first():
    phase = FakePhase(gamma_texts=["garbage", "still garbage"])
    subset = [(_ev(1, 1), ["RCC_PROBE x"]), (_ev(2, 0), [])]
    full = [_ev(100, 0)]
    mem = FakeMemory()
    tr, _ = _run(phase, subset, full, memory=mem)
    assert tr.orchestration_outcome == "green"
    assert _phases_called(phase) == ["alpha", "beta", "gamma", "gamma-retry",
                                     "fix-1"]
    ev = "\n".join(_events(tr))
    assert "degraded to subgraph-order ranking" in ev
    # degraded run has no graph -> nothing saved to memory even on green
    assert mem.puts == []
    # fix-1 focused on the target (first in subgraph order)
    fix_prompt_text = [p for (n, p, _t) in phase.calls if n == "fix-1"][0]
    assert "p.C.put" in fix_prompt_text and "no causal graph" in fix_prompt_text


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
        RccConfig(target_label="p.C.put"), _SLICE, _METHODS, initial=_ev(0, 2),
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
