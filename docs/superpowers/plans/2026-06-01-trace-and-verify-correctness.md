# Trace + Verify Correctness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make finished + live traces render the REAL OpenCode event shape (correct tool/read/search/edit counts, file edits, readable per-turn stats, authoritative metrics, test results), enrich metrics (in/out/reasoning/cache tokens, tests-actually-executed, opencode cost), and make verify run the right build/test command via ambiguity-aware detection + a usable UI override — proven with real Gradle/Maven builds.

**Architecture:** Backend already normalizes raw events into `trace.json` (`steps`+`turns`) and `metrics.json` correctly; the frontend was parsing a guessed raw shape (→ zeros). Fix: render finished traces from the normalized `trace.json` + `metrics.json`; render the live stream from a real-shape raw normalizer; one shared `UiTurn` model. Add token/cache/tests-executed metrics in the backend extractor + `report.NUMERIC`. Replace first-match build detection with ambiguity-aware `detect_verify` (Gradle stray-`pom.xml` fix) + a usable verify section in the form.

**Tech Stack:** Python 3.12 (pydantic, subprocess/git, real gradle/mvn), FastAPI, React 18 + TS + MUI v5 + TanStack Query, pytest, Vitest + MSW.

**Spec:** `docs/superpowers/specs/2026-06-01-trace-and-verify-correctness-design.md`

**Conventions:** Python tests `.venv/bin/pytest`. Frontend from `web/`: `npm test -- --run`, `npx tsc -b`. tsconfig `strict` + `noUncheckedIndexedAccess`. Stay on `main`. Commit per task. Two env-dependent real-opencode e2e tests (`tests/test_run_e2e.py::test_abench_run_e2e`, `tests/test_opencode_client_integration.py::test_real_client_runs_trivial_task`) fail in this sandbox regardless — deselect in full-suite runs.

**Real OpenCode shape (authority: `trace_normalize.py` + `tests/fixtures/opencode/events_sample.jsonl`):** raw event has outer `type` (`tool_use`/`text`/`reasoning`/`step_finish`/`step_start`/`patch`) and `part` with `part.type` ∈ {`tool`,`text`,`reasoning`,`step-finish`,`step-start`,`patch`}, `part.messageID`. `tool`: `part.tool`, `part.callID`, `part.state.{status,input,output,metadata.exit,time}`. `text`/`reasoning`: `part.text`. `patch`: `part.path`,`part.patch`. `step-finish`: `part.tokens.{input,output,reasoning,cache:{read,write}}`, `part.cost`, `part.reason`, `part.time`. Session export `info.tokens={input,output,reasoning,cache:{read,write}}`, `info.cost`.

---

## Task 1: Backend — capture reasoning + cache tokens

**Files:** Modify `abench/trace_model.py`, `abench/trace_normalize.py`; Test `tests/test_trace_normalize.py` (append).

- [ ] **Step 1: Write the failing test**

Append to `tests/test_trace_normalize.py` (mirror its existing imports/style):
```python
def test_normalize_captures_reasoning_and_cache_tokens():
    from abench.trace_normalize import normalize
    session = {"info": {"tokens": {"input": 100, "output": 20, "reasoning": 5,
                                    "cache": {"read": 80, "write": 12}}, "cost": 0.01}}
    tr = normalize([], session)
    assert tr.tokens_in == 100 and tr.tokens_out == 20
    assert tr.tokens_reasoning == 5
    assert tr.cache_read == 80 and tr.cache_write == 12
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_trace_normalize.py -k reasoning_and_cache -v`
Expected: FAIL — `Trace` has no `tokens_reasoning`/`cache_read`/`cache_write`.

- [ ] **Step 3: Add Trace fields + capture them**

In `abench/trace_model.py` `Trace`, after `cost: float | None = None` (the trace-level token block), add:
```python
    tokens_reasoning: int | None = None
    cache_read: int | None = None
    cache_write: int | None = None
```
In `abench/trace_normalize.py`, replace the session-export block:
```python
    if raw_session is not None:
        info = raw_session.get("info", {})
        tokens = info.get("tokens", {})
        tokens_in = tokens.get("input")
        tokens_out = tokens.get("output")
        cost = info.get("cost")
```
with:
```python
    tokens_reasoning: int | None = None
    cache_read: int | None = None
    cache_write: int | None = None
    if raw_session is not None:
        info = raw_session.get("info", {})
        tokens = info.get("tokens", {})
        tokens_in = tokens.get("input")
        tokens_out = tokens.get("output")
        tokens_reasoning = tokens.get("reasoning")
        cache = tokens.get("cache", {}) or {}
        cache_read = cache.get("read")
        cache_write = cache.get("write")
        cost = info.get("cost")
```
And pass them into the `Trace(...)` return (add the three kwargs).

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_trace_normalize.py -k reasoning_and_cache -v` → PASS.

- [ ] **Step 5: Commit**

```bash
git add abench/trace_model.py abench/trace_normalize.py tests/test_trace_normalize.py
git commit -m "feat(trace): capture reasoning + cache token totals from session export"
```

---

## Task 2: Backend — `n_tests_executed` + emit new tokens; `report.NUMERIC`

**Files:** Modify `abench/metrics.py`, `abench/report.py`; Test `tests/test_metrics.py` (append).

- [ ] **Step 1: Write the failing test**

Append to `tests/test_metrics.py`:
```python
def test_n_tests_executed_parses_test_command_output():
    from abench.metrics import extract, MetricsConfig
    from abench.trace_model import Step, StepKind, Trace
    cfg = MetricsConfig(
        test_command_patterns=["pytest"], shell_tool_names=["bash"],
        read_tool_names=["read"], search_tool_names=["grep"],
        command_arg_keys=["command"],
    )
    tr = Trace(steps=[
        Step(kind=StepKind.TOOL_CALL, tool_name="bash", tool_call_id="c1",
             tool_args={"command": "pytest -q"}),
        Step(kind=StepKind.TOOL_RESULT, tool_call_id="c1",
             output="5 passed, 1 failed in 0.3s"),
    ])
    m = extract(tr, "", cfg)
    assert m["n_test_runs"] == 1            # one invocation
    assert m["n_tests_executed"] == 6       # 5 passed + 1 failed parsed from output
    assert m["tokens_reasoning"] is None    # absent on this trace
    assert "cache_read" in m and "cache_write" in m


def test_n_tests_executed_zero_when_unparseable():
    from abench.metrics import extract, MetricsConfig
    from abench.trace_model import Step, StepKind, Trace
    cfg = MetricsConfig(test_command_patterns=["pytest"], shell_tool_names=["bash"],
                        read_tool_names=["read"], search_tool_names=["grep"],
                        command_arg_keys=["command"])
    tr = Trace(steps=[
        Step(kind=StepKind.TOOL_CALL, tool_name="bash", tool_call_id="c1",
             tool_args={"command": "pytest"}),
        Step(kind=StepKind.TOOL_RESULT, tool_call_id="c1", output="weird output"),
    ])
    m = extract(tr, "", cfg)
    assert m["n_test_runs"] == 1 and m["n_tests_executed"] == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_metrics.py -k tests_executed -v`
Expected: FAIL — `n_tests_executed` key missing.

- [ ] **Step 3: Implement in `metrics.py`**

In `abench/metrics.py`, add an import at top: `from .verify import _parser_for` (the test-output parser selector).

After the `n_test` invocation-count loop, add a tests-executed computation. First build a tool_call_id → result-output map, then parse test-command outputs:
```python
    # Map tool_call_id → result output, to read each test command's output.
    result_output: dict[str, str] = {}
    for s in trace.steps:
        if s.kind == StepKind.TOOL_RESULT and s.tool_call_id is not None:
            result_output[s.tool_call_id] = s.output or ""

    n_tests_executed = 0
    for s in tool_calls:
        if s.tool_name in cfg.shell_tool_names:
            cmd = _command_of(s, cfg.command_arg_keys)
            if any(r.search(cmd) for r in test_res):
                parser = _parser_for(cmd)  # keyed on the command's first token
                out = result_output.get(s.tool_call_id or "", "")
                if parser is not None and out:
                    try:
                        passed, failed, _names = parser(out)
                        n_tests_executed += passed + failed
                    except ValueError:
                        pass
```
In the returned dict, after `"n_test_runs": n_test,` add:
```python
        "n_tests_executed": n_tests_executed,
```
and after the token block add:
```python
        "tokens_reasoning": trace.tokens_reasoning,
        "cache_read": trace.cache_read,
        "cache_write": trace.cache_write,
```

In `abench/report.py`, extend `NUMERIC` with the new aggregatable keys:
```python
NUMERIC = [
    "duration_s", "n_steps", "n_tool_calls", "n_test_runs", "n_tests_executed",
    "n_reads", "n_searches", "n_files_edited", "diff_lines_added", "diff_lines_removed",
    "tokens_in", "tokens_out", "tokens_reasoning", "cache_read", "cache_write",
    "cost", "time_to_first_edit_s",
]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_metrics.py -k "tests_executed or verify_reason or success" -v`
Expected: PASS. (`_parser_for("pytest -q")` → `parse_pytest_output`; "5 passed, 1 failed" → (5,1,...).)

- [ ] **Step 5: Commit**

```bash
git add abench/metrics.py abench/report.py tests/test_metrics.py
git commit -m "feat(metrics): n_tests_executed + reasoning/cache tokens; aggregate them"
```

---

## Task 3: Backend — ambiguity-aware `detect_verify` (Gradle stray-pom fix)

**Files:** Modify `abench/verify.py`, `abench_ui/server.py`; Test `tests/test_verify.py` (append), `tests/abench_ui/test_verify_api.py` (append).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_verify.py`:
```python
def test_detect_verify_gradle_only(tmp_path):
    from abench.verify import detect_verify
    (tmp_path / "build.gradle").write_text("")
    (tmp_path / "gradlew").write_text("")
    d = detect_verify(tmp_path)
    assert d.system == "gradle" and d.command == "./gradlew test"
    assert d.ambiguous is False


def test_detect_verify_maven_only(tmp_path):
    from abench.verify import detect_verify
    (tmp_path / "pom.xml").write_text("<project/>")
    d = detect_verify(tmp_path)
    assert d.system == "maven" and d.command == "mvn test" and d.ambiguous is False


def test_detect_verify_picocli_like_prefers_gradle_and_flags_ambiguous(tmp_path):
    # Gradle project that ALSO ships a root pom.xml (the picocli bug).
    from abench.verify import detect_verify
    (tmp_path / "build.gradle").write_text("")
    (tmp_path / "settings.gradle").write_text("")
    (tmp_path / "gradlew").write_text("")
    (tmp_path / "pom.xml").write_text("<project/>")
    d = detect_verify(tmp_path)
    assert d.system == "gradle" and d.command == "./gradlew test"
    assert d.ambiguous is True
    assert set(d.candidates) == {"gradle", "maven"}


def test_detect_command_shim(tmp_path):
    from abench.verify import detect_command
    (tmp_path / "pom.xml").write_text("<project/>")
    assert detect_command(tmp_path) == "mvn test"
    assert detect_command(tmp_path / "empty") is None
```
Append to `tests/abench_ui/test_verify_api.py`:
```python
def test_verify_command_endpoint_reports_ambiguity(tmp_path):
    from fastapi.testclient import TestClient
    from abench_ui.server import create_app
    exp_dir = tmp_path / "experiments"; d = exp_dir / "exp"
    (d / "fix").mkdir(parents=True)
    (d / "fix" / "build.gradle").write_text("")
    (d / "fix" / "gradlew").write_text("")
    (d / "fix" / "pom.xml").write_text("<project/>")
    (d / "ref").mkdir(); (d / "prompts").mkdir()
    (d / "prompts" / "task.md").write_text("t"); (d / "prompts" / "system.md").write_text("s")
    (d / "experiment.yaml").write_text(
        "name: exp\nfixture_path: ./fix\nreference_path: ./ref\n"
        "task_prompt: ./prompts/task.md\nsystem_prompt: ./prompts/system.md\n"
        "model: m\nrepetitions: 1\noutput_dir: ./runs\n"
        "conditions:\n  - {name: baseline, augmentation: null}\n")
    client = TestClient(create_app(experiments_dir=exp_dir))
    body = client.get("/api/experiments/exp/verify_command").json()
    assert body["system"] == "gradle" and body["command"] == "./gradlew test"
    assert body["ambiguous"] is True
    assert set(body["candidates"]) == {"gradle", "maven"}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_verify.py -k detect_verify -v`
Expected: FAIL — `detect_verify` missing.

- [ ] **Step 3: Implement `detect_verify` + `detect_command` shim**

In `abench/verify.py`, replace the existing `detect_command` with:
```python
@dataclass
class DetectResult:
    command: str | None
    system: str | None
    ambiguous: bool = False
    candidates: list[str] = field(default_factory=list)


def _gradle_command(workdir: Path) -> str:
    return "./gradlew test" if (workdir / "gradlew").exists() else "gradle test"


def _maven_command(workdir: Path) -> str:
    return "./mvnw test" if (workdir / "mvnw").exists() else "mvn test"


def detect_verify(workdir: Path) -> DetectResult:
    """Detect build system(s). When both Gradle and Maven are present (e.g. a
    Gradle project carrying a stray root pom.xml — picocli), prefer Gradle and
    flag ambiguity so the UI can prompt for an explicit command."""
    workdir = Path(workdir)
    has_gradle = any((workdir / f).exists() for f in
                     ("build.gradle", "build.gradle.kts", "settings.gradle",
                      "settings.gradle.kts", "gradlew"))
    has_maven = (workdir / "pom.xml").exists() or (workdir / "mvnw").exists()
    has_pytest = (workdir / "pyproject.toml").exists() and (workdir / "tests").is_dir()

    candidates: list[str] = []
    if has_gradle:
        candidates.append("gradle")
    if has_maven:
        candidates.append("maven")
    if has_pytest:
        candidates.append("pytest")

    if has_gradle and has_maven:
        return DetectResult(command=_gradle_command(workdir), system="gradle",
                            ambiguous=True, candidates=candidates)
    if has_gradle:
        return DetectResult(command=_gradle_command(workdir), system="gradle",
                            candidates=candidates)
    if has_maven:
        return DetectResult(command=_maven_command(workdir), system="maven",
                            candidates=candidates)
    if has_pytest:
        return DetectResult(command="pytest", system="pytest", candidates=candidates)
    return DetectResult(command=None, system=None, candidates=[])


def detect_command(workdir: Path) -> str | None:
    """Back-compat: the canonical command, or None."""
    return detect_verify(workdir).command
```
(Keep `Status`, `VerifyResult`, parsers, `run_verify`, `write_verify_log` unchanged. `detect_command`'s callers — `runner._detect_verify`, `reverify` — keep working via the shim.)

In `abench_ui/server.py`, in the `/experiments/{name}/verify_command` handler, switch to the rich result:
```python
    @api.get("/experiments/{name}/verify_command")
    def _detect_verify_command(name: str):
        from abench.config import load_experiment
        from abench.verify import detect_verify

        exp_dir = _exp_dir_for(name)
        yaml_path = exp_dir / "experiment.yaml"
        if not yaml_path.is_file():
            raise HTTPException(404, f"experiment '{name}' not found")
        try:
            exp = load_experiment(yaml_path)
            if exp.verify.command:
                return {"command": exp.verify.command, "system": _verify_system_label(exp.verify.command),
                        "ambiguous": False, "candidates": []}
            d = detect_verify(exp.fixture_path)
            return {"command": d.command, "system": d.system,
                    "ambiguous": d.ambiguous, "candidates": d.candidates}
        except Exception:
            return {"command": None, "system": None, "ambiguous": False, "candidates": []}
```
(`_verify_system_label` already exists from the verify-diagnostics work.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_verify.py -k "detect" tests/abench_ui/test_verify_api.py -k ambiguity -v`
Expected: PASS.

- [ ] **Step 5: Full Python suite (no regression)**

Run: `.venv/bin/pytest -q --deselect tests/test_run_e2e.py::test_abench_run_e2e --deselect tests/test_opencode_client_integration.py::test_real_client_runs_trivial_task`
Expected: green (runner/reverify still use `detect_command` shim).

- [ ] **Step 6: Commit**

```bash
git add abench/verify.py abench_ui/server.py tests/test_verify.py tests/abench_ui/test_verify_api.py
git commit -m "feat(verify): ambiguity-aware detect_verify (Gradle stray-pom fix) + rich endpoint"
```

---

## Task 4: Real Gradle/Maven build smokes (the user's "прям проверь")

**Files:** Test `tests/test_verify_real_builds.py` (create).

- [ ] **Step 1: Write the integration tests (skip if toolchain absent)**

`tests/test_verify_real_builds.py`:
```python
import shutil
import textwrap
from pathlib import Path

import pytest

from abench.verify import detect_verify, run_verify

GRADLE = shutil.which("gradle")
MVN = shutil.which("mvn")
JAVA = shutil.which("java")


@pytest.mark.skipif(not (GRADLE and JAVA), reason="gradle/java not on PATH")
def test_real_gradle_project_detects_and_runs(tmp_path):
    (tmp_path / "settings.gradle").write_text("rootProject.name='demo'\n")
    (tmp_path / "build.gradle").write_text(textwrap.dedent("""
        plugins { id 'java' }
        repositories { mavenCentral() }
        dependencies { testImplementation 'junit:junit:4.13.2' }
        test { useJUnit() }
    """))
    td = tmp_path / "src/test/java/demo"; td.mkdir(parents=True)
    (td / "AppTest.java").write_text(textwrap.dedent("""
        package demo; import org.junit.Test; import static org.junit.Assert.*;
        public class AppTest { @Test public void ok(){ assertEquals(2, 1+1); } }
    """))
    d = detect_verify(tmp_path)
    assert d.system == "gradle"
    v = run_verify(tmp_path, "gradle test", timeout_s=600)
    assert v.status == "passed", v.message
    assert v.passed_count and v.passed_count >= 1


@pytest.mark.skipif(not (MVN and JAVA), reason="mvn/java not on PATH")
def test_real_maven_project_detects_and_runs(tmp_path):
    (tmp_path / "pom.xml").write_text(textwrap.dedent("""
        <project xmlns="http://maven.apache.org/POM/4.0.0"><modelVersion>4.0.0</modelVersion>
        <groupId>demo</groupId><artifactId>demo</artifactId><version>1</version>
        <dependencies><dependency><groupId>junit</groupId><artifactId>junit</artifactId>
        <version>4.13.2</version><scope>test</scope></dependency></dependencies></project>
    """))
    td = tmp_path / "src/test/java/demo"; td.mkdir(parents=True)
    (td / "AppTest.java").write_text(textwrap.dedent("""
        package demo; import org.junit.Test; import static org.junit.Assert.*;
        public class AppTest { @Test public void ok(){ assertEquals(2, 1+1); } }
    """))
    d = detect_verify(tmp_path)
    assert d.system == "maven"
    v = run_verify(tmp_path, "mvn -q test", timeout_s=600)
    assert v.status == "passed", v.message
    assert v.passed_count and v.passed_count >= 1


@pytest.mark.skipif(not (GRADLE and JAVA), reason="gradle/java not on PATH")
def test_picocli_like_ambiguous_picks_gradle_not_maven(tmp_path):
    # build.gradle + gradlew-less but a stray pom.xml → must pick gradle, not mvn.
    (tmp_path / "settings.gradle").write_text("rootProject.name='demo'\n")
    (tmp_path / "build.gradle").write_text(textwrap.dedent("""
        plugins { id 'java' } repositories { mavenCentral() }
        dependencies { testImplementation 'junit:junit:4.13.2' } test { useJUnit() }
    """))
    (tmp_path / "pom.xml").write_text("<project><broken/>")  # would fail `mvn test`
    td = tmp_path / "src/test/java/demo"; td.mkdir(parents=True)
    (td / "AppTest.java").write_text(
        "package demo; import org.junit.Test; import static org.junit.Assert.*;"
        " public class AppTest { @Test public void ok(){ assertEquals(2,1+1);} }")
    d = detect_verify(tmp_path)
    assert d.system == "gradle" and d.ambiguous is True
    v = run_verify(tmp_path, d.command, timeout_s=600)
    assert v.status == "passed", v.message
```

- [ ] **Step 2: Run the smokes**

Run: `.venv/bin/pytest tests/test_verify_real_builds.py -v`
Expected: the gradle + ambiguous tests PASS (real build runs; first run downloads deps — allow time). If a tool is missing they skip. Report the actual output (status + counts) in the task report. (If a real build is too slow for CI, that's fine — these are skip-guarded and run on a dev machine with the toolchain.)

- [ ] **Step 3: Commit**

```bash
git add tests/test_verify_real_builds.py
git commit -m "test(verify): real Gradle/Maven build smokes + picocli-like ambiguity"
```

---

## Task 5: Frontend — Step type, trace UI model (`turnsFromTrace` + `turnsFromRawEvents`)

**Files:** Modify `web/src/api/types.ts`; Create `web/src/lib/traceModel.ts`; Test `web/tests/traceModel.test.ts`.

- [ ] **Step 1: Add types**

In `web/src/api/types.ts`:
```ts
export type StepKind =
  | "assistant_text" | "reasoning" | "tool_call" | "tool_result" | "file_edit";

export interface Step {
  kind: StepKind;
  ts: number | null;
  turn: number | null;
  text?: string | null;
  tool_name?: string | null;
  tool_args?: Record<string, unknown> | null;
  tool_call_id?: string | null;
  output?: string | null;
  exit_code?: number | null;
  path?: string | null;
  patch?: string | null;
}
```
Add `steps: Step[];` to the `Trace` interface, and to `MetricsJson` add:
`n_tests_executed?: number | null; tokens_reasoning?: number | null; cache_read?: number | null; cache_write?: number | null;`. Add the same four to `ConditionSummary`'s metric keys are dynamic (Record), so no change there.

- [ ] **Step 2: Write the failing test**

`web/tests/traceModel.test.ts`:
```ts
import { expect, test } from "vitest";
import { turnsFromTrace, turnsFromRawEvents } from "../src/lib/traceModel";
import type { Step } from "../src/api/types";

const steps: Step[] = [
  { kind: "reasoning", ts: 1, turn: 0, text: "thinking" },
  { kind: "tool_call", ts: 2, turn: 0, tool_name: "read", tool_args: { path: "a.py" }, tool_call_id: "c1" },
  { kind: "tool_result", ts: 3, turn: 0, tool_call_id: "c1", output: "file body", exit_code: 0 },
  { kind: "file_edit", ts: 4, turn: 0, path: "a.py", patch: "@@\n-x\n+y\n" },
  { kind: "assistant_text", ts: 5, turn: 1, text: "done" },
];
const turnInfos = [
  { message_id: "M0", reason: "tool-calls", tokens_in: 100, tokens_out: 20, tokens_reasoning: 5, cost: 0.001, started_at: 1, ended_at: 4 },
  { message_id: "M1", reason: "stop", tokens_in: 40, tokens_out: 8, tokens_reasoning: 0, cost: 0.0005, started_at: 5, ended_at: 6 },
];

test("turnsFromTrace groups steps by turn, pairs tool call+result, joins TurnInfo", () => {
  const turns = turnsFromTrace({ steps, turns: turnInfos } as any);
  expect(turns).toHaveLength(2);
  expect(turns[0]!.parts.find((p) => p.kind === "tool")).toMatchObject({
    name: "read", ok: true, output: "file body",
  });
  expect(turns[0]!.parts.some((p) => p.kind === "edit")).toBe(true);
  expect(turns[0]!.reason).toBe("tool-calls");
  expect(turns[0]!.tokensIn).toBe(100);
});

test("turnsFromRawEvents maps the REAL opencode shape", () => {
  const raw = [
    { part: { type: "reasoning", messageID: "M0", text: "thinking" } },
    { part: { type: "tool", messageID: "M0", tool: "read", callID: "c1",
              state: { status: "completed", input: { path: "a.py" }, output: "file body",
                       metadata: { exit: 0 } } } },
    { part: { type: "patch", messageID: "M0", path: "a.py", patch: "@@\n-x\n+y\n" } },
    { part: { type: "step-finish", messageID: "M0", reason: "tool-calls",
              tokens: { input: 100, output: 20, reasoning: 5 }, cost: 0.001 } },
  ];
  const turns = turnsFromRawEvents(raw);
  expect(turns).toHaveLength(1);
  const tool = turns[0]!.parts.find((p) => p.kind === "tool");
  expect(tool).toMatchObject({ name: "read", ok: true, output: "file body" });
  expect(turns[0]!.parts.some((p) => p.kind === "edit")).toBe(true);
  expect(turns[0]!.reason).toBe("tool-calls");
  expect(turns[0]!.tokensIn).toBe(100);
});
```

- [ ] **Step 3: Run test to verify it fails**

Run: `npm test -- --run tests/traceModel.test.ts` → FAIL (module missing).

- [ ] **Step 4: Implement `web/src/lib/traceModel.ts`**

```ts
import type { Step, Trace } from "../api/types";

export type UiPart =
  | { kind: "reasoning" | "text"; text: string }
  | { kind: "tool"; name: string; args: Record<string, unknown>; output: string | null; exitCode: number | null; ok: boolean | null }
  | { kind: "edit"; path: string; patch: string };

export interface UiTurn {
  index: number;
  messageId: string | null;
  reason: string | null;
  tokensIn: number | null;
  tokensOut: number | null;
  tokensReasoning: number | null;
  cost: number | null;
  durationS: number | null;
  parts: UiPart[];
}

function emptyTurn(index: number): UiTurn {
  return { index, messageId: null, reason: null, tokensIn: null, tokensOut: null,
    tokensReasoning: null, cost: null, durationS: null, parts: [] };
}

// ── From the normalized trace.json (finished runs — authoritative) ──────────
export function turnsFromTrace(trace: Pick<Trace, "steps" | "turns">): UiTurn[] {
  const byTurn = new Map<number, UiTurn>();
  const ensure = (i: number) => {
    let t = byTurn.get(i);
    if (!t) { t = emptyTurn(i); byTurn.set(i, t); }
    return t;
  };
  // index → result step (for pairing tool_call with its tool_result)
  const resultByCall = new Map<string, Step>();
  for (const s of trace.steps) {
    if (s.kind === "tool_result" && s.tool_call_id) resultByCall.set(s.tool_call_id, s);
  }
  for (const s of trace.steps) {
    if (s.turn == null) continue;
    const t = ensure(s.turn);
    if (s.kind === "reasoning") t.parts.push({ kind: "reasoning", text: s.text ?? "" });
    else if (s.kind === "assistant_text") t.parts.push({ kind: "text", text: s.text ?? "" });
    else if (s.kind === "file_edit") t.parts.push({ kind: "edit", path: s.path ?? "", patch: s.patch ?? "" });
    else if (s.kind === "tool_call") {
      const res = s.tool_call_id ? resultByCall.get(s.tool_call_id) : undefined;
      const exitCode = res?.exit_code ?? null;
      t.parts.push({
        kind: "tool", name: s.tool_name ?? "?", args: s.tool_args ?? {},
        output: res?.output ?? null,
        exitCode,
        ok: exitCode == null ? null : exitCode === 0,
      });
    }
    // tool_result steps are folded into their tool_call; skip standalone.
  }
  // join TurnInfo by order: the Nth TurnInfo (Nth step-finish) corresponds to
  // turn index N (trace_normalize assigns turn = order of messageID first-appearance,
  // and step-finish events append in that same order).
  trace.turns.forEach((ti, idx) => {
    const t = ensure(idx);
    t.messageId = ti.message_id ?? null;
    t.reason = ti.reason ?? null;
    t.tokensIn = ti.tokens_in ?? null;
    t.tokensOut = ti.tokens_out ?? null;
    t.tokensReasoning = ti.tokens_reasoning ?? null;
    t.cost = ti.cost ?? null;
    t.durationS = (ti.started_at != null && ti.ended_at != null)
      ? ti.ended_at - ti.started_at : null;
  });
  return [...byTurn.values()].sort((a, b) => a.index - b.index);
}

// ── From raw OpenCode events (live stream — no normalized trace yet) ────────
export function turnsFromRawEvents(rawEvents: any[]): UiTurn[] {
  const order: string[] = [];
  const byId = new Map<string, UiTurn>();
  const ensure = (mid: string) => {
    let t = byId.get(mid);
    if (!t) { t = emptyTurn(order.length); t.messageId = mid; byId.set(mid, t); order.push(mid); }
    return t;
  };
  for (const ev of rawEvents) {
    const p = ev?.part ?? {};
    const mid = p.messageID;
    if (!mid) continue;
    const t = ensure(mid);
    if (p.type === "reasoning") t.parts.push({ kind: "reasoning", text: String(p.text ?? "") });
    else if (p.type === "text") t.parts.push({ kind: "text", text: String(p.text ?? "") });
    else if (p.type === "patch") t.parts.push({ kind: "edit", path: String(p.path ?? ""), patch: String(p.patch ?? "") });
    else if (p.type === "tool") {
      const st = p.state ?? {};
      const exitRaw = st.metadata?.exit;
      const exitCode = typeof exitRaw === "number" ? exitRaw : null;
      const ok = st.status === "error" ? false : exitCode == null ? (st.status === "completed" ? true : null) : exitCode === 0;
      t.parts.push({
        kind: "tool", name: String(p.tool ?? "?"), args: st.input ?? {},
        output: st.output != null ? String(st.output) : null, exitCode, ok,
      });
    } else if (p.type === "step-finish") {
      const tk = p.tokens ?? {};
      t.reason = p.reason ?? t.reason;
      t.tokensIn = tk.input ?? t.tokensIn;
      t.tokensOut = tk.output ?? t.tokensOut;
      t.tokensReasoning = tk.reasoning ?? t.tokensReasoning;
      t.cost = p.cost ?? t.cost;
    }
  }
  return order.map((mid) => byId.get(mid)!);
}

// Per-turn breakdown by real tool name: { read: 3, grep: 2, edit: 1 }.
export function toolBreakdown(turn: UiTurn): Record<string, number> {
  const out: Record<string, number> = {};
  for (const p of turn.parts) {
    if (p.kind === "tool") out[p.name] = (out[p.name] ?? 0) + 1;
    else if (p.kind === "edit") out["edit"] = (out["edit"] ?? 0) + 1;
  }
  return out;
}
```

- [ ] **Step 5: Run test to verify it passes + typecheck**

Run: `npm test -- --run tests/traceModel.test.ts` → PASS. `npx tsc -b` → clean.

- [ ] **Step 6: Commit**

```bash
git add web/src/api/types.ts web/src/lib/traceModel.ts web/tests/traceModel.test.ts
git commit -m "feat(ui/web): Step type + UiTurn trace model (turnsFromTrace/turnsFromRawEvents)"
```

---

## Task 6: Frontend — TurnCard renders `UiTurn`

**Files:** Modify `web/src/components/TurnCard.tsx`; Test `web/tests/TurnCard.test.tsx` (rewrite).

- [ ] **Step 1: Rewrite `TurnCard` to take a `UiTurn`**

Replace `web/src/components/TurnCard.tsx` so it accepts `{ turn: UiTurn; index: number; rawEvents: unknown[] }` and renders from `turn.parts`:
```tsx
import { useState } from "react";
import { Card, CardContent, Stack, Typography, Chip, Box, Button } from "@mui/material";
import RawEventsToggle from "./RawEventsToggle";
import { formatTokens } from "../lib/formatTokens";
import { selectable } from "../theme";
import { toolBreakdown, type UiTurn } from "../lib/traceModel";

interface Props { turn: UiTurn; index: number; rawEvents: unknown[]; }

const COLLAPSE = 600;

function argSummary(args: Record<string, unknown>): string {
  for (const k of ["command", "filePath", "path", "pattern", "query"]) {
    const v = args[k];
    if (typeof v === "string") return v.slice(0, 160);
  }
  const j = JSON.stringify(args);
  return j === "{}" ? "" : j.slice(0, 160);
}

function Long({ text, prefix, accent }: { text: string; prefix: string; accent: string }) {
  const [open, setOpen] = useState(false);
  const long = text.length > COLLAPSE;
  const shown = open || !long ? text : text.slice(0, COLLAPSE) + "…";
  return (
    <Box sx={{ borderLeft: 2, borderColor: accent, pl: 1.5, py: 0.25 }}>
      <Typography variant="body2" sx={{ whiteSpace: "pre-wrap", ...selectable }}>{prefix} {shown}</Typography>
      {long && <Button size="small" onClick={() => setOpen(!open)} sx={{ mt: 0.25 }}>{open ? "show less" : "show more"}</Button>}
    </Box>
  );
}

export default function TurnCard({ turn, index, rawEvents }: Props) {
  const breakdown = toolBreakdown(turn);
  const breakdownStr = Object.entries(breakdown).map(([n, c]) => `${n} ×${c}`).join(" · ") || "no tools";
  return (
    <Card variant="outlined">
      <CardContent>
        <Stack direction="row" alignItems="center" spacing={1} sx={{ mb: 1.5 }} flexWrap="wrap">
          <Chip size="small" variant="outlined" label={`turn ${index + 1}`} />
          {turn.reason && <Chip size="small" color="primary" label={turn.reason} />}
          <Box sx={{ flexGrow: 1 }} />
          <Typography variant="caption" color="text.secondary">
            in {formatTokens(turn.tokensIn)} · out {formatTokens(turn.tokensOut)}
            {turn.cost != null && <> · ${turn.cost.toFixed(4)}</>}
            {turn.durationS != null && <> · {turn.durationS.toFixed(1)}s</>}
          </Typography>
        </Stack>

        <Stack spacing={1.25}>
          {turn.parts.map((p, i) => {
            if (p.kind === "reasoning") return <Long key={i} prefix="💭" accent="info.main" text={p.text} />;
            if (p.kind === "text") return <Long key={i} prefix="🗨" accent="text.primary" text={p.text} />;
            if (p.kind === "edit") return (
              <Box key={i} sx={{ borderLeft: 2, borderColor: "warning.main", pl: 1.5 }}>
                <Typography variant="body2" sx={selectable}><b>📝 {p.path}</b></Typography>
                <Typography variant="caption" component="pre" sx={{ m: 0, whiteSpace: "pre-wrap", ...selectable }}>
                  {p.patch.slice(0, 400)}
                </Typography>
              </Box>
            );
            // tool
            return (
              <Box key={i} sx={{ borderLeft: 2, borderColor: p.ok === false ? "error.main" : "success.main", pl: 1.5, ...selectable }}>
                <Typography variant="body2">
                  <b>{p.ok === false ? "✗" : p.ok ? "✓" : "✎"} {p.name}</b> {argSummary(p.args)}
                  {p.exitCode != null && p.exitCode !== 0 && <> · exit {p.exitCode}</>}
                </Typography>
                {p.output && (
                  <Typography variant="caption" color="text.secondary" sx={{ whiteSpace: "pre-wrap", ...selectable }}>
                    → {p.output.slice(0, 300)}
                  </Typography>
                )}
              </Box>
            );
          })}
        </Stack>

        <Typography variant="caption" color="text.secondary" sx={{ display: "block", mt: 1.5 }}>
          {breakdownStr}
        </Typography>
        <RawEventsToggle events={rawEvents} />
      </CardContent>
    </Card>
  );
}
```

- [ ] **Step 2: Rewrite the test**

Replace `web/tests/TurnCard.test.tsx`:
```tsx
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, test } from "vitest";
import TurnCard from "../src/components/TurnCard";
import type { UiTurn } from "../src/lib/traceModel";

const turn: UiTurn = {
  index: 0, messageId: "M0", reason: "tool-calls",
  tokensIn: 11700, tokensOut: 118, tokensReasoning: 5, cost: 0.0017, durationS: 62,
  parts: [
    { kind: "reasoning", text: "thinking about it" },
    { kind: "tool", name: "read", args: { path: "a.py" }, output: "file body", exitCode: 0, ok: true },
    { kind: "tool", name: "grep", args: { pattern: "foo" }, output: "match", exitCode: 0, ok: true },
    { kind: "edit", path: "a.py", patch: "@@\n-x\n+y\n" },
  ],
};

test("renders tool calls with name+args+result, edits, and a real-name breakdown", async () => {
  render(<TurnCard turn={turn} index={0} rawEvents={[{ part: { type: "tool" } }]} />);
  expect(screen.getByText(/turn 1/)).toBeInTheDocument();
  expect(screen.getByText(/✓ read/)).toBeInTheDocument();
  expect(screen.getByText(/✓ grep/)).toBeInTheDocument();
  expect(screen.getByText(/📝 a\.py/)).toBeInTheDocument();
  expect(screen.getByText(/read ×1 · grep ×1 · edit ×1/)).toBeInTheDocument();
  expect(screen.getByText(/in 11\.7k · out 118/)).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: /show raw/i }));
  expect(screen.getByText(/"type":"tool"/)).toBeInTheDocument();
});
```

- [ ] **Step 3: Run test + typecheck**

Run: `npm test -- --run tests/TurnCard.test.tsx` → PASS. (`npx tsc -b` may fail at TraceView's old call site — fixed in Task 7; run tsc after Task 7.)

- [ ] **Step 4: Commit**

```bash
git add web/src/components/TurnCard.tsx web/tests/TurnCard.test.tsx
git commit -m "feat(ui/web): TurnCard renders UiTurn (real tools/edits, name breakdown, readable stats)"
```

---

## Task 7: Frontend — TraceView from normalized trace; live Run from raw normalizer; AggregateStatsBar

**Files:** Modify `web/src/pages/TraceView.tsx`, `web/src/components/AggregateStatsBar.tsx`, `web/src/pages/Run.tsx` (+ `web/src/components/EventStream.tsx`). Test: adjust existing.

- [ ] **Step 1: Rewrite `AggregateStatsBar` to take metrics (authoritative + tooltips)**

Replace `web/src/components/AggregateStatsBar.tsx`:
```tsx
import { Stack, Typography, Tooltip } from "@mui/material";
import { formatTokens } from "../lib/formatTokens";
import type { MetricsJson } from "../api/types";

interface Props { metrics: MetricsJson; }

const HELP: Record<string, string> = {
  steps: "Distinct model steps (turns) in the ReAct chain — one LLM round-trip each (reasoning + tool calls or final text). Fewer for the same outcome = more efficient.",
  "tool calls": "Total tool invocations across the run.",
  "test runs": "How many times the agent invoked a test command.",
  "tests run": "Individual tests those commands actually exercised (parsed from output).",
  reads: "read/open file operations.",
  searches: "grep/glob/list operations — code exploration volume.",
  tokens: "Prompt tokens read (in) / generated (out) over the whole run.",
  cache: "Tokens served from the provider's prompt cache. With run isolation (nonce prefix) on, expect ≈0.",
  cost: "$ at the provider's rates (from opencode).",
};

function Stat({ label, value, help }: { label: string; value: string; help: string }) {
  return (
    <Tooltip title={help}>
      <Typography variant="body2" color="text.secondary" sx={{ cursor: "help" }}>
        {label}: <b>{value}</b>
      </Typography>
    </Tooltip>
  );
}

export default function AggregateStatsBar({ metrics: m }: Props) {
  const num = (v: unknown) => (typeof v === "number" ? v : null);
  return (
    <Stack direction="row" spacing={2} flexWrap="wrap" alignItems="center">
      <Stat label="steps" value={String(num(m.n_steps) ?? "—")} help={HELP.steps} />
      <Stat label="tool calls" value={String(num(m.n_tool_calls) ?? "—")} help={HELP["tool calls"]} />
      <Stat label="reads" value={String(num(m.n_reads) ?? "—")} help={HELP.reads} />
      <Stat label="searches" value={String(num(m.n_searches) ?? "—")} help={HELP.searches} />
      <Stat label="test runs" value={String(num(m.n_test_runs) ?? "—")} help={HELP["test runs"]} />
      <Stat label="tests run" value={String(num(m.n_tests_executed) ?? "—")} help={HELP["tests run"]} />
      <Stat label="tokens" value={`${formatTokens(num(m.tokens_in))} in / ${formatTokens(num(m.tokens_out))} out`} help={HELP.tokens} />
      <Stat label="cache" value={`${formatTokens(num(m.cache_read))} r / ${formatTokens(num(m.cache_write))} w`} help={HELP.cache} />
      <Stat label="cost" value={`$${(num(m.cost) ?? 0).toFixed(4)}`} help={HELP.cost} />
    </Stack>
  );
}
```
(`MetricsJson` has an index signature, so `m.n_tests_executed` etc. are accessible; the `num()` guard handles `unknown`.)

- [ ] **Step 2: Rewrite `TraceView`**

In `web/src/pages/TraceView.tsx`: add `useMetrics`; build turns via `turnsFromTrace(trace.data)`; render `AggregateStatsBar metrics={metrics.data}` (guard while loading); render `TurnCard` from the UiTurns (rawEvents per turn still sourced from `events.data` filtered by messageId, for "show raw"). Key body:
```tsx
import { useTrace, useEvents, useMetrics, useRuns } from "../api/queries";
import { turnsFromTrace } from "../lib/traceModel";
// ...
  const metrics = useMetrics(name!, condition!, repN);
  const uiTurns = turnsFromTrace(trace.data);
  const rawByMsg = (mid: string | null) =>
    (events.data ?? []).filter((e: any) => e?.part?.messageID === mid);
// ...
  {metrics.data && <AggregateStatsBar metrics={metrics.data} />}
  {uiTurns.map((t) => (
    <TurnCard key={t.messageId ?? t.index} turn={t} index={t.index} rawEvents={rawByMsg(t.messageId)} />
  ))}
```
Remove the old `groupEventsByTurn`-based mapping for the timeline (keep `useEvents` only for the raw toggle). VerdictBanner/VerifyCard/baseline warning/FinalDiff/MethodComparison/MetricsDrawer stay.

- [ ] **Step 3: Fix the live Run page**

In `web/src/pages/Run.tsx` (and/or `EventStream.tsx`): replace the `groupEventsByTurn` timeline with `turnsFromRawEvents(rawEvents)` rendered via `TurnCard` (same UiTurn). The live aggregate counters (`derived` reducer) already count `run.finished`/verify envelopes — leave those; only the per-turn event rendering switches to the real-shape normalizer. Keep the dark terminal "show raw".

- [ ] **Step 4: Update/remove dependent tests**

`groupEventsByTurn` + its test, `EventStream` + its test, and the old `AggregateStatsBar` usage: update to the new model. `groupEventsByTurn.ts` becomes unused → delete it and its test (the live + finished paths now use `traceModel`). If `EventStream` is now only the raw view, simplify or fold into `TurnCard`'s raw toggle. Adjust `web/tests/EventStream.test.tsx`/`groupEventsByTurn.test.ts` accordingly (delete if the module is removed).

- [ ] **Step 5: Run full suite + typecheck**

Run: `npm test -- --run` → all green. `npx tsc -b` → clean.

- [ ] **Step 6: Commit**

```bash
git add web/src/pages/TraceView.tsx web/src/pages/Run.tsx web/src/components/AggregateStatsBar.tsx \
        web/src/components/EventStream.tsx web/src/lib/groupEventsByTurn.ts web/tests/
git commit -m "feat(ui/web): render trace from normalized trace + real-shape live stream; metric tooltips"
```

---

## Task 8: Frontend — enriched comparison (SummaryTable directions + new rows)

**Files:** Modify `web/src/lib/metricLabels.ts`, `web/src/components/SummaryTable.tsx`; Test `web/tests/SummaryTable.test.tsx` (extend).

- [ ] **Step 1: Update `metricLabels.ts`**

```ts
// "direction" decides delta coloring: lower=better → negative Δ green; higher=better
// → positive Δ green; neutral → never colored (informational).
export type Direction = "lower" | "higher" | "neutral";
export const SUMMARY_METRICS: { key: string; label: string; direction: Direction; help?: string }[] = [
  { key: "n_steps", label: "steps", direction: "lower" },
  { key: "n_reads", label: "reads", direction: "lower" },
  { key: "n_searches", label: "searches", direction: "lower" },
  { key: "n_test_runs", label: "test runs", direction: "lower" },
  { key: "n_tests_executed", label: "tests executed", direction: "neutral",
    help: "Individual tests the agent ran — more isn't inherently better." },
  { key: "duration_s", label: "duration (s)", direction: "lower" },
  { key: "time_to_first_edit_s", label: "time to first edit (s)", direction: "lower" },
  { key: "n_tool_calls", label: "tool calls", direction: "lower" },
  { key: "tokens_in", label: "tokens read (in)", direction: "lower" },
  { key: "tokens_out", label: "tokens generated (out)", direction: "lower" },
  { key: "tokens_reasoning", label: "reasoning tokens", direction: "lower" },
  { key: "cache_read", label: "cache read", direction: "neutral",
    help: "From the provider's prompt cache; ≈0 expected with run isolation on." },
  { key: "cost", label: "cost ($)", direction: "lower" },
];
```

- [ ] **Step 2: Update `SummaryTable` delta coloring + tooltips**

In `web/src/components/SummaryTable.tsx`, replace the `lowerIsBetter` logic:
```tsx
            const delta = summary.deltas[m.key];
            const good = delta != null && delta !== 0 &&
              (m.direction === "lower" ? delta < 0 : m.direction === "higher" ? delta > 0 : false);
            const bad = delta != null && delta !== 0 && m.direction !== "neutral" && !good;
```
and wrap the metric-label cell in a `<Tooltip title={m.help ?? ""}>` when `m.help` is set (import `Tooltip`). The success-rate row + structure stay.

- [ ] **Step 3: Extend the test**

In `web/tests/SummaryTable.test.tsx`, add `tokens_in`/`tokens_out`/`cache_read` to the fixture conditions' metrics + `deltas`, and assert: `tokens read (in)` row renders; a `lower` metric with negative Δ is green-colored (assert the cell text `-NN.N%`); a `neutral` metric (`cache_read`) Δ is NOT colored success/error (assert it renders but, if practical, that its color is the neutral token). Keep existing assertions.

- [ ] **Step 4: Run test + full suite + typecheck**

Run: `npm test -- --run` → green. `npx tsc -b` → clean.

- [ ] **Step 5: Commit**

```bash
git add web/src/lib/metricLabels.ts web/src/components/SummaryTable.tsx web/tests/SummaryTable.test.tsx
git commit -m "feat(ui/web): comparison adds tokens in/out/reasoning, tests-executed, cache (neutral) + tooltips"
```

---

## Task 9: Frontend — usable verify section (detected system + ambiguity + override)

**Files:** Modify `web/src/api/types.ts` (DetectedVerify +ambiguous/candidates), `web/src/components/FixturesPanel.tsx`, `web/src/pages/ExperimentEdit.tsx`; Test `web/tests/FixturesPanel.test.tsx` (create or extend).

- [ ] **Step 1: Extend `DetectedVerify`**

In `web/src/api/types.ts`, extend:
```ts
export interface DetectedVerify {
  command: string | null;
  system: "maven" | "gradle" | "pytest" | "custom" | null;
  ambiguous: boolean;
  candidates: string[];
}
```

- [ ] **Step 2: FixturesPanel shows detection + ambiguity**

In `web/src/components/FixturesPanel.tsx`, extend the build row to take `verifyAmbiguous?: boolean` and `verifyCandidates?: string[]`, and render the ambiguity warning:
```tsx
          <Stack direction="row" spacing={1} alignItems="center" flexWrap="wrap">
            <Typography variant="body2">
              <b>build/verify:</b>{" "}
              {verifyCommand
                ? <>{verifySystem ?? "custom"} · <code>{verifyCommand}</code></>
                : <i>no build system detected — set <code>verify.command</code></i>}
            </Typography>
            {verifyAmbiguous && (
              <Typography variant="caption" color="warning.main">
                ⚠ ambiguous ({(verifyCandidates ?? []).join(" + ")}) — using {verifySystem};
                set verify.command if wrong
              </Typography>
            )}
          </Stack>
```
Add the two props to the interface + destructuring.

- [ ] **Step 3: ExperimentEdit passes detection + the override field is usable**

In `web/src/pages/ExperimentEdit.tsx`: pass `verifyAmbiguous={detected.data?.ambiguous ?? false}` and `verifyCandidates={detected.data?.candidates ?? []}` to `<FixturesPanel/>`.
For the `verify.command` field rendering as a meaningless `anyOf` dropdown: add a uiSchema entry so it renders as a plain text field with help. In `web/src/schema/uiSchema.ts`, add under the verify object:
```ts
  verify: {
    command: {
      "ui:help": "Build/test command. Leave blank to auto-detect; override for e.g. ./gradlew test, mvn -q test, pytest -q.",
      "ui:placeholder": "auto-detect",
    },
  },
```
If the rjsf `anyOf` dropdown for `Optional[str]` persists despite the uiSchema, collapse it: in `web/src/api/schemaCache.ts` (where the schema is loaded), post-process to rewrite any `{anyOf:[{type:"string"},{type:"null"}]}` (and the reverse order) into `{type:"string"}` so nullable strings render as a single text field. (Verify which file loads/normalizes the schema; apply the collapse there.) Add a unit test for the collapse helper.

- [ ] **Step 4: Test**

`web/tests/FixturesPanel.test.tsx`: render with `verifyCommand="mvn test"`, `verifySystem="maven"`, `verifyAmbiguous` true, candidates ["gradle","maven"] → assert the command + the "⚠ ambiguous (gradle + maven)" text appear; and with `verifyCommand={null}` → the "no build system detected" hint. If you add the anyOf-collapse helper, unit-test it (anyOf[string,null] → {type:string}).

- [ ] **Step 5: Run full suite + typecheck**

Run: `npm test -- --run` → green. `npx tsc -b` → clean.

- [ ] **Step 6: Commit**

```bash
git add web/src/api/types.ts web/src/components/FixturesPanel.tsx web/src/pages/ExperimentEdit.tsx \
        web/src/schema/uiSchema.ts web/src/api/schemaCache.ts web/tests/FixturesPanel.test.tsx
git commit -m "feat(ui/web): usable verify command field + detected build system + ambiguity warning"
```

---

## Task 10: Integration — build, suites, boot smoke

**Files:** none (verification).

- [ ] **Step 1: Frontend suite + typecheck + build** — `cd web && npm test -- --run && npx tsc -b && npm run build` → green/clean/built.
- [ ] **Step 2: Python suite** — `.venv/bin/pytest -q --deselect tests/test_run_e2e.py::test_abench_run_e2e --deselect tests/test_opencode_client_integration.py::test_real_client_runs_trivial_task` → green. (Real-build smokes run if toolchain present.)
- [ ] **Step 3: Boot + render smoke (synthetic).** Seed a finished run whose `trace.json` carries real-shape `steps` (a `tool_call`+`tool_result` pair + a `file_edit`) and a `metrics.json` with non-zero `n_reads`/`n_tests_executed`/`cache_read`. Boot `abench-ui`, open the trace, confirm via `preview_eval` (or curl + DOM check) that tool name/result/edit render and counts are non-zero (not the old all-zero). Confirm `/api/experiments/<name>/verify_command` returns `{command,system,ambiguous,candidates}`.
- [ ] **Step 4: Manual browser smoke (human).** Open a real finished run: tool calls show name/args/result/exit; file edits show; per-turn breakdown is real; aggregate metrics labeled with tooltips; tokens in/out + cache visible; verify section shows detected system + ambiguity + editable command. (If you can't run a browser, say so.)
- [ ] **Step 5: Final commit (if smoke fixes needed)** — `git add -A && git commit -m "fix: trace+verify correctness smoke fixes"` (skip if none).

---

## Self-review notes (for the executor)

- **Single source of truth:** finished TraceView renders from `trace.json` `steps`/`turns` (backend-normalized, fixture-tested) + `metrics.json` (authoritative aggregates). The live page uses `turnsFromRawEvents` (the real shape) since there's no trace mid-run. Both feed `UiTurn` → one `TurnCard`.
- **The bug fixed:** old code matched `part.type === "tool-call"`/`name`; real is `type: "tool"`/`tool`/`state.input` + `type: "patch"` edits → that's why counts were 0. Tasks 5-7 fix both surfaces.
- **Types line up:** TS `Step`/`StepKind` mirror the backend dataclasses; `MetricsJson` gains `n_tests_executed`/`tokens_reasoning`/`cache_read`/`cache_write` (also added to `report.NUMERIC` so `/summary` aggregates them); `DetectedVerify` gains `ambiguous`/`candidates` matching the endpoint.
- **`detect_command` shim** keeps `runner`/`reverify` callers working unchanged; only the endpoint uses the rich `detect_verify`.
- **Real builds verified** in Task 4 (gradle + maven + picocli-like ambiguity), gated to skip if the toolchain is absent — the dev machine has `gradle`/`mvn`/`java`.
- **Old runs render fine:** `trace.json` has always serialized `steps` (the runner wrote `to_dict()`), so existing finished runs light up without a re-run; if `steps` were ever empty, the timeline is empty but metrics/verify still show.
