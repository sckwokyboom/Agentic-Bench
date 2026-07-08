# tests/test_rcc_graph.py
import json

import pytest

pytest.importorskip("langgraph")   # optional extra — skip cleanly without it

from abench.orchestrator import PhaseOutcome, SuiteEval
from abench.rcc_graph import RccConfig, run_rcc
from abench.rcc_subgraph import RccSubgraph
from abench.regression_gate import SuiteResult
from abench.trace_model import StepKind, Trace

_SUB = RccSubgraph(
    target_fqn="p.C.put", methods=["p.C.put", "p.C.get"],
    test_fqns=["p.CT.t1", "p.CT.t2"], test_classes=["p.CT"],
    sources={"p.C.put": "Object put() { return null; }"},
)

_GAMMA = json.dumps({
    "nodes": [{"id": "p.C.put", "type": "method"},
              {"id": "p.C.get", "type": "method"}],
    "edges": [{"src": "p.C.put", "tgt": "p.C.get", "type": "causal",
               "weight": 0.9, "reason": "put returns null -> get NPE"}],
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
        cfg or RccConfig(target_label="p.C.put"), _SUB, initial=_ev(0, 2),
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


def test_full_suite_red_consumes_attempt():
    phase = FakePhase()
    subset = [(_ev(1, 1), []),                 # beta
              (_ev(2, 0), []),                 # fix-1 subset green
              (_ev(2, 0), [])]                 # fix-2 subset green
    full = [_ev(90, 10), _ev(100, 0)]          # fix-1 full red -> fix-2 full green
    tr, _ = _run(phase, subset, full)
    assert tr.orchestration_outcome == "green"
    assert _phases_called(phase)[-2:] == ["fix-1", "fix-2"]
