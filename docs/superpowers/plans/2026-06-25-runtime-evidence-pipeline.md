# Runtime Evidence Pipeline — Host Card + `phased-runtime` (Plan 2 of 2)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the probe's capture (`.runtime-capture.jsonl`) into a tight, ranked **diagnostic card** auto-injected into the phased DIAGNOSE prompt, as a new condition **`phased-runtime`** — comparable by trace to `phased` / `phased_graph`.

**Architecture:** The phased DIAGNOSE loop runs the suite as a host gradle subprocess. For `phased_runtime` we attach the (host-built) probe jar to that subprocess via `JAVA_TOOL_OPTIONS`, writing the capture to a file OUTSIDE the workdir (so git restore/clean can't wipe it). A pure host module parses + ranks the capture into a card; the orchestrator reads it (before the per-round restore) and prepends it to the diagnose prompt. The ONLY difference vs `phased` is that extra card → clean ablation.

**Tech Stack:** Python (host) + the existing Byte Buddy agent (Plan 1, built on the host via gradle). Decisions locked: host-built agent jar + `JAVA_TOOL_OPTIONS`; the spike's inline `String.valueOf` arg rendering (safe-summarizer is a later enhancement).

**Prereq:** Plan 1 is GO (the probe captures a real corridor + args + throw). A real sample capture line is recorded in `docker/runtime-probe/README.md` — used as the test fixture below.

> **AS-BUILT NOTE (2026-06-25, Tasks 1–5 done).** One divergence from the Task 5
> draft below: the probe's target FQN is supplied by an **explicit config field**
> `OrchestrationCfg.probe_targets` (full binary FQNs, e.g.
> `picocli.CommandLine$Help$TextTable.putValue`), NOT derived from `coverage.json`.
> This removes the graph-overlay coupling (cleaner ablation) and resolves the "FQN
> must match the coverage key" live risk in the self-review — the FQN is stated
> directly and was confirmed by the spike's captured frame. So the
> `_probe_target`/coverage.json helper in Task 5 Step 2 was NOT added; the runner
> uses `",".join(exp.orchestration.probe_targets or [])` and degrades to plain
> phased (logged) when the jar or targets are absent. All other tasks match the
> draft. Tests green: `test_runtime_evidence.py` (5), `test_orchestration_adapters.py`
> (+2), `test_orchestrator.py` (+2).

---

## File Structure

- Create: `abench/runtime_evidence.py` — pure: parse capture JSONL → events → trim corridor → dedup/rank → render card.
- Create: `tests/test_runtime_evidence.py` — TDD for the above (real-sample fixture).
- Modify: `abench/orchestration_adapters.py` — `make_suite_runner` gains optional probe env (clear capture + set `JAVA_TOOL_OPTIONS`); add `build_evidence_reader(...)`.
- Modify: `abench/orchestrator.py` — `run(...)` gains `read_evidence: Callable[[], str|None]`; diagnose loop reads it (before restore) + `diagnose_prompt(..., evidence_card=...)` prepends it.
- Modify: `abench/runner.py` — `phased_runtime` branch: locate host agent jar, wire probed suite + evidence reader.
- Modify: `abench/config.py` — orchestration mode doc += `phased_runtime`.
- Modify: `experiments/picocli-putValue/experiment.yaml` — `phased-runtime` condition.
- Modify: `tests/test_orchestrator.py` — diagnose injects the card when `read_evidence` is provided.

---

## Task 1: Capture parser + corridor trim (TDD)

**Files:**
- Create: `abench/runtime_evidence.py`
- Test: `tests/test_runtime_evidence.py`

- [ ] **Step 1: Write the failing test**

```python
from abench.runtime_evidence import parse_capture, trim_corridor, CaptureEvent

_REAL = (
    '{"method":"picocli.CommandLine$Help$TextTable.putValue","args":["0","0",""],'
    '"stack":["picocli.CommandLine$Help$TextTable.putValue:17415",'
    '"picocli.CommandLine$Help$TextTable.addRowValues:17380",'
    '"picocli.CommandLine$Help.join:16325","picocli.CommandLine.usage:2795",'
    '"picocli.HelpTest.testCatUsageFormat:2331","org.junit.runners.model.X.run:1"]}\n'
    '{"method":"picocli.CommandLine$Help$TextTable.putValue","exit":true,'
    '"throw":"java.lang.UnsupportedOperationException: TODO: implement putValue"}\n'
)

def test_parse_capture(tmp_path):
    f = tmp_path / "cap.jsonl"; f.write_text(_REAL)
    events = parse_capture(f)
    assert len(events) == 2
    enter = events[0]
    assert enter.method.endswith("putValue") and enter.args == ["0", "0", ""]
    assert enter.exit is False and enter.thrown is None
    assert events[1].exit is True
    assert "UnsupportedOperationException" in events[1].thrown

def test_parse_capture_tolerant(tmp_path):
    f = tmp_path / "cap.jsonl"; f.write_text('not json\n{"no":"method"}\n\n')
    assert parse_capture(f) == []
    assert parse_capture(tmp_path / "missing.jsonl") == []   # absent file → []

def test_trim_corridor_drops_framework_frames():
    stack = ["picocli.CommandLine$Help$TextTable.putValue:17415",
             "picocli.CommandLine.usage:2795",
             "picocli.HelpTest.testCatUsageFormat:2331",
             "org.junit.runners.model.X.run:1",
             "jdk.internal.reflect.Y.invoke:1"]
    out = trim_corridor(stack)
    assert out[0].endswith("putValue:17415")
    assert any("HelpTest.testCatUsageFormat" in f for f in out)   # test frame kept
    assert all("org.junit" not in f and "jdk." not in f for f in out)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_runtime_evidence.py -q`
Expected: FAIL — `abench.runtime_evidence` does not exist.

- [ ] **Step 3: Write minimal implementation**

```python
"""Host-side: turn the runtime probe's capture (.runtime-capture.jsonl) into a
tight, ranked diagnostic card for the phased DIAGNOSE prompt (phased-runtime
ablation). Pure + tolerant: a malformed/empty/absent capture yields no card."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

# Frames to drop from a corridor — test framework / JVM internals / the probe.
_DROP = ("org.junit", "org.gradle", "worker.org", "jdk.", "java.", "sun.",
         "javax.", "net.bytebuddy", "abench.probe")


@dataclass
class CaptureEvent:
    method: str
    args: list[str] = field(default_factory=list)
    stack: list[str] = field(default_factory=list)
    thrown: "str | None" = None
    exit: bool = False


def parse_capture(path) -> list[CaptureEvent]:
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    out: list[CaptureEvent] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if not isinstance(d, dict) or "method" not in d:
            continue
        out.append(CaptureEvent(
            method=str(d.get("method", "")),
            args=[str(a) for a in (d.get("args") or [])],
            stack=[str(s) for s in (d.get("stack") or [])],
            thrown=d.get("throw"),
            exit=bool(d.get("exit")),
        ))
    return out


def trim_corridor(stack: list[str], keep: int = 6) -> list[str]:
    """Keep the top app frames (closest to the method), dropping framework/JVM."""
    return [f for f in stack if not f.startswith(_DROP)][:keep]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_runtime_evidence.py -q`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add abench/runtime_evidence.py tests/test_runtime_evidence.py
git commit -m "feat(runtime-evidence): tolerant capture parser + corridor trim"
```

---

## Task 2: Dedup/rank + diagnostic card (TDD)

**Files:**
- Modify: `abench/runtime_evidence.py`
- Test: `tests/test_runtime_evidence.py`

- [ ] **Step 1: Write the failing test** (append)

```python
from abench.runtime_evidence import build_card

def test_build_card_dedups_and_caps(tmp_path):
    f = tmp_path / "cap.jsonl"; f.write_text(_REAL + _REAL)   # duplicate call
    events = parse_capture(f)
    card = build_card(events, "TextTable.putValue", max_examples=3)
    assert card is not None
    assert "RUNTIME EVIDENCE for TextTable.putValue" in card
    assert card.count("args:") == 1                       # duplicate (corridor,args) deduped
    assert "0, 0, (empty)" in card or "0, 0," in card     # args rendered
    assert "corridor:" in card and "putValue:17415" in card
    assert "HelpTest.testCatUsageFormat" in card          # test frame in corridor
    assert "UnsupportedOperationException" in card        # throw surfaced
    assert "do not curve-fit" in card                     # evidence-not-fix framing
    assert "fix by" not in card.lower()                   # never prescribes a fix

def test_build_card_none_when_empty():
    assert build_card([], "TextTable.putValue") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_runtime_evidence.py -q`
Expected: FAIL — `build_card` not defined.

- [ ] **Step 3: Write minimal implementation** (append to `runtime_evidence.py`)

```python
def build_card(events: list[CaptureEvent], target_label: str, *,
               max_examples: int = 3, corridor_keep: int = 6) -> "str | None":
    """A tight, provenance-marked diagnostic card from this run's capture.
    Evidence only — never prescribes a fix (else the ablation would measure our
    heuristic, not the value of the evidence)."""
    enters = [e for e in events if not e.exit]
    exits = [e for e in events if e.exit]
    if not enters and not exits:
        return None

    seen: set = set()
    uniq: list[tuple[tuple, list[str]]] = []
    for e in enters:
        corr = tuple(trim_corridor(e.stack, corridor_keep))
        key = (corr, tuple(e.args))
        if key in seen:
            continue
        seen.add(key)
        uniq.append((corr, e.args))

    throws = sorted({e.thrown for e in exits if e.thrown})

    lines = [
        f"RUNTIME EVIDENCE for {target_label} "
        f"(captured THIS run; src: method-entry probe — actual values + call path):",
        f"  observed {len(enters)} call(s); {len(uniq)} distinct path/arg shape(s)",
    ]
    for i, (corr, args) in enumerate(uniq[:max_examples], 1):
        shown = ", ".join(a if a != "" else "(empty)" for a in args) if args else "(no args)"
        lines.append(f"  [{i}] args: {shown}")
        if corr:
            lines.append("      corridor: " + " <- ".join(corr))
    for t in throws[:2]:
        lines.append(f"  throws: {t}")
    lines.append("  (evidence only — find the COMMON root cause; do not curve-fit a single call)")
    return "\n".join(lines)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_runtime_evidence.py -q`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add abench/runtime_evidence.py tests/test_runtime_evidence.py
git commit -m "feat(runtime-evidence): ranked diagnostic card (dedup, cap, evidence-not-fix)"
```

---

## Task 3: Probed suite runner + evidence reader

**Files:**
- Modify: `abench/orchestration_adapters.py`

- [ ] **Step 1: Add probe env to `make_suite_runner`** (clear capture + set JAVA_TOOL_OPTIONS)

Change the signature + body of `make_suite_runner` to accept an optional probe config:

```python
import os

def make_suite_runner(workdir: Path, command: str, timeout_s: int,
                      probe: "dict | None" = None) -> Callable[[], SuiteEval]:
    """Host subprocess (like verify) + JUnit XML breakdown. Clears stale results
    first. When `probe` is given (keys: jar, targets, out), attaches the runtime
    probe to the test JVM via JAVA_TOOL_OPTIONS and clears the capture file so
    each call reflects only its own run."""
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
                                  capture_output=True, text=True, timeout=timeout_s, env=env)
            out = (proc.stdout or "") + "\n" + (proc.stderr or "")
        except (subprocess.TimeoutExpired, OSError):
            return SuiteEval(result=SuiteResult(compiled=True, ran=False, executed=0,
                                                passed=0, failed=0))
        ev = eval_from_junit(workdir, compiled=True, ran=True)
        compiled, ran = build_status(out, ev.result.executed)
        ev.result.compiled = compiled
        ev.result.ran = ran
        return ev

    return runner
```

- [ ] **Step 2: Add the evidence reader factory** (append to `orchestration_adapters.py`)

```python
def build_evidence_reader(capture_path, target_label: str) -> "Callable[[], str | None]":
    """A read_evidence() the orchestrator calls each diagnose round: parse the
    latest capture into a card (None if nothing captured)."""
    from .runtime_evidence import parse_capture, build_card

    def read() -> "str | None":
        return build_card(parse_capture(capture_path), target_label)

    return read
```

- [ ] **Step 3: Verify the module imports + existing adapter tests pass**

Run: `python3 -m pytest tests/test_orchestration_adapters.py -q`
Expected: PASS (probe defaults to None → existing behaviour unchanged).

- [ ] **Step 4: Commit**

```bash
git add abench/orchestration_adapters.py
git commit -m "feat(runtime-evidence): probed suite runner (JAVA_TOOL_OPTIONS) + evidence reader"
```

---

## Task 4: Orchestrator injects the card into DIAGNOSE (TDD)

**Files:**
- Modify: `abench/orchestrator.py`
- Test: `tests/test_orchestrator.py`

- [ ] **Step 1: Write the failing test** (append to `tests/test_orchestrator.py`)

```python
def test_phased_runtime_injects_evidence_card_into_diagnose():
    """phased-runtime: read_evidence() supplies a card that appears in the diagnose
    prompt (and is recorded as a controller event), without changing the outcome."""
    suite = _fake_suite([_eval(0, 100), _eval(0, 100), _eval(100, 0)])
    snap, restore, _ = _snap_restore()
    prompts = {}

    def phase(name, prompt, tools):
        prompts[name] = prompt
        return PhaseOutcome(_trace_with_reads(2), _CONTRACT.get(name, ""))

    t = run(_CFG, phase_runner=phase, suite_runner=suite, snapshot=snap, restore=restore,
            read_evidence=lambda: "RUNTIME EVIDENCE for TextTable.putValue: args [0,0]")
    assert "RUNTIME EVIDENCE" in prompts["diagnose"]           # card reached the agent
    assert t.orchestration_outcome == "green"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_orchestrator.py::test_phased_runtime_injects_evidence_card_into_diagnose -q`
Expected: FAIL — `run()` has no `read_evidence` kwarg.

- [ ] **Step 3: Implement** — three edits in `abench/orchestrator.py`:

(a) `diagnose_prompt` gains an `evidence_card` param that prepends the card:

```python
def diagnose_prompt(cfg: OrchestratorConfig, contract: str, plan: str,
                    clusters: list[Cluster], graph_focused: bool = False,
                    evidence_card: "str | None" = None) -> str:
    body = "\n".join(_fmt_cluster(c) for c in clusters)
    focus = (f" These clusters are tests that EXERCISE {cfg.target_label} "
             "(your change's blast radius — per the call graph)." if graph_focused else "")
    card = (evidence_card + "\n\n") if evidence_card else ""
    return (card + "The full suite still fails. Here is ONE example per failure cluster "
            f"(across classes).{focus} Find the COMMON root cause and make ONE fix "
            f"to {cfg.target_label} — do not curve-fit a single test.\n\n"
            f"FAILURE CLUSTERS:\n{body}\n\nCONTRACT (for reference):\n{contract}")
```

(b) `run(...)` signature gains the injected reader:

```python
def run(
    cfg: OrchestratorConfig,
    *,
    phase_runner: PhaseRunner,
    suite_runner: SuiteRunner,
    snapshot: Callable[[], object],
    restore: Callable[[object], None],
    on_event: "Callable[[dict], None] | None" = None,
    in_blast_radius: "Callable[[TestFailure], bool] | None" = None,
    read_evidence: "Callable[[], str | None] | None" = None,
) -> Trace:
```

(c) in the DIAGNOSE loop, read the card BEFORE `safe_restore` (restore's `git clean`
would wipe an in-workdir capture; the capture path is outside the workdir, but read
first anyway so the card reflects the latest suite run), and pass it to the prompt.
Replace the loop body head:

```python
        it += 1
        card = None
        if read_evidence is not None:
            try:
                card = read_evidence()
            except Exception:
                card = None
            if card:
                event(f"runtime evidence: injected {len(card.splitlines())}-line card", "diagnose")
        safe_restore(best_tree)
        all_clusters = cluster_failures(best.failures)
        graph_focused = False
        if in_blast_radius is not None:
            in_r = [c for c in all_clusters if in_blast_radius(c.representative)]
            if in_r:
                event(f"graph: focusing diagnose on {len(in_r)}/{len(all_clusters)} "
                      f"failure clusters inside {cfg.target_label}'s blast radius", "diagnose")
                all_clusters = in_r
                graph_focused = True
            else:
                event(f"graph: no failing clusters in {cfg.target_label}'s blast radius "
                      f"— using all {len(all_clusters)}", "diagnose")
        clusters = select_clusters(all_clusters, cfg.cluster_cap)
        d = do_phase("diagnose",
                     diagnose_prompt(cfg, contract, plan, clusters,
                                     graph_focused=graph_focused, evidence_card=card),
                     ["read", "edit", "verify"])
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_orchestrator.py -q`
Expected: PASS (all, incl. the new test). The card controller event is CONTROLLER-kind
→ already excluded from metrics, so the comparison stays clean.

- [ ] **Step 5: Commit**

```bash
git add abench/orchestrator.py tests/test_orchestrator.py
git commit -m "feat(runtime-evidence): inject diagnostic card into the diagnose prompt"
```

---

## Task 5: Runner wiring for `phased_runtime` + config + experiment

**Files:**
- Modify: `abench/runner.py`, `abench/config.py`, `experiments/picocli-putValue/experiment.yaml`

- [ ] **Step 1: Locate the host agent jar (build helper)** — add to `abench/runner.py` (module level)

```python
def _runtime_probe_jar() -> "str | None":
    """The host-built probe agent jar (Plan 1). Built via:
        cd docker/runtime-probe && gradle jar
    Returns the absolute path if present, else None (→ phased_runtime degrades to
    plain phased, logged)."""
    from pathlib import Path as _P
    jar = _P(__file__).resolve().parent.parent / "docker" / "runtime-probe" / "build" / "libs" / "runtime-probe-agent.jar"
    return str(jar) if jar.is_file() else None
```

- [ ] **Step 2: Wire the phased_runtime branch** in `_run_one` — extend the orchestrate branch (right where `in_blast_radius` is built) to build the probed suite + reader:

```python
                    # phased_runtime ablation: attach the runtime probe to the
                    # suite JVM + feed a diagnostic card into diagnose. Best-effort:
                    # if the agent jar isn't built, degrade to plain phased.
                    read_evidence = None
                    if cond.orchestration == "phased_runtime":
                        from .orchestration_adapters import build_evidence_reader
                        from .runtime_evidence import build_card  # noqa: F401 (import check)
                        jar = _runtime_probe_jar()
                        if jar and exp.target_methods:
                            cap = str(rundir / "runtime-capture.jsonl")  # OUTSIDE workdir
                            targets = ",".join(
                                f"{exp.orchestration.target_label.rsplit('.', 1)[0] if '.' in exp.orchestration.target_label else 'picocli.CommandLine$Help$TextTable'}.{m}"
                                if False else _probe_target(exp, m) for m in exp.target_methods)
                            suite_runner = make_suite_runner(
                                workdir, suite_cmd, exp.verify.timeout_s,
                                probe={"jar": jar, "targets": targets, "out": cap})
                            read_evidence = build_evidence_reader(cap, exp.orchestration.target_label)
                        else:
                            _log("[abench] phased_runtime: probe jar/targets missing — plain phased")
```

with a target-FQN helper (module level in `runner.py`):

```python
def _probe_target(exp, method: str) -> str:
    """Fully-qualified target for the probe: '<declaring-class-fqn>.<method>'. Use
    the coverage.json key whose method matches, else fall back to target_label."""
    import json
    from pathlib import Path as _P
    try:
        cov = json.loads((_P(exp.fixture_path).parent / "overlays" / "impact-artifacts"
                          / ".impact" / "coverage.json").read_text())
        for fqn in cov:
            if fqn.rsplit(".", 1)[-1] == method:
                return fqn
    except Exception:
        pass
    return method
```

Then pass `read_evidence=read_evidence` into the `_orchestrate(...)` call (alongside
`in_blast_radius=in_blast_radius`).

- [ ] **Step 3: Config doc** — in `abench/config.py`, extend the `orchestration` description to mention `phased_runtime` (one line: "`phased_runtime` = phased + a runtime diagnostic card (probe) injected into diagnose").

- [ ] **Step 4: Experiment condition** — append to `experiments/picocli-putValue/experiment.yaml` conditions:

```yaml
  # Ablation: phased + a runtime diagnostic card (the probe) injected into diagnose.
  # Requires the host agent jar: cd docker/runtime-probe && gradle jar
  - name: phased-runtime
    augmentation: ./slices/impact-tool-briefing.md
    overlay: ./overlays/impact-artifacts
    tools: [impact]
    orchestration: phased_runtime
```

- [ ] **Step 5: Verify config loads + runner imports**

Run:
```bash
python3 -c "from abench.config import load_experiment; e=load_experiment('experiments/picocli-putValue/experiment.yaml'); print([c.orchestration for c in e.conditions])"
python3 -m pytest tests/test_runner.py tests/test_config_orchestration.py -q
```
Expected: `phased_runtime` present; tests pass.

- [ ] **Step 6: Commit**

```bash
git add abench/runner.py abench/config.py experiments/picocli-putValue/experiment.yaml
git commit -m "feat(runtime-evidence): phased_runtime condition (probed suite + card)"
```

---

## Task 6: End-to-end smoke (WSL)

**Files:** none (manual, on WSL — docker + the host agent jar).

- [ ] **Step 1: Build the host agent jar**

Run: `cd docker/runtime-probe && gradle jar && ls build/libs/runtime-probe-agent.jar`
Expected: jar present (this is what `_runtime_probe_jar()` finds).

- [ ] **Step 2: Run `phased-runtime` via the UI / CLI on putValue (1 rep)**

Confirm in the trace: the DIAGNOSE controller cards include "runtime evidence: injected
N-line card", and the diagnose turn's prompt (or the live stream) shows the card with a
real corridor + args. Compare by trace to `phased` / `phased_graph`.

- [ ] **Step 3: Sanity** — `phased` (no probe) still produces no card; metrics (`n_steps`
etc.) match across conditions (the card is a CONTROLLER event, excluded).

---

## Self-Review

**Spec coverage** (`2026-06-24-runtime-evidence-probe-design.md`):
- Probe capture → Plan 1 (done, GO). ✓
- Retrieval + ranker + card (provenance, evidence-not-fix, capped) → Tasks 1–2. ✓
- Auto-push into diagnose → Task 4. ✓
- `phased-runtime` condition, metric-neutral (CONTROLLER event) → Tasks 4–5. ✓
- Public-tests-only / no oracle leak → unchanged (the probe only observes the suite the agent already runs). ✓
- Safe summarizer → deliberately deferred (locked decision: inline args first); noted in `docker/runtime-probe/README.md`. Not a gap.

**Placeholder scan:** no TBD/TODO; every step has runnable code/commands. The capture
fixture is the real Plan-1 sample.

**Type consistency:** `parse_capture`→`CaptureEvent`→`build_card`→`build_evidence_reader`
(returns `read_evidence`) → `orchestrator.run(read_evidence=...)` → `diagnose_prompt(evidence_card=...)`
are consistent. `make_suite_runner(probe={jar,targets,out})` keys match the runner's dict.

**Known live risk (resolve at Task 6, not a plan defect):** the `_probe_target` FQN must
match the coverage.json key for putValue (`picocli.CommandLine$Help$TextTable.putValue`) —
verified to exist in the data; the fallback is `target_methods` bare names.
