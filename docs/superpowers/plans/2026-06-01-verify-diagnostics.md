# Verify Diagnostics (Phase 1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make a failed `verify` explain itself — classify the failure (build_failed / tool_not_found / tests_failed+counts / no_tests / timeout / unparseable) with a short reason + message, persist a full `verify_output.log` reachable from the UI, show the detected build system, and warn loudly when the untouched reference project itself fails verify.

**Architecture:** Additive — keep the `verify_status` contract `{passed,failed,skipped,error,timeout}` and `metrics.success` logic unchanged; add `reason` + `message` alongside, persist full output to a log file, and surface everything in the UI. Backend changes in `abench/verify.py` (classifier), `abench/runner.py` (log + baseline), `abench/metrics.py` + `abench/trace_model.py` (propagation), `abench_ui/server.py` (2 endpoints). Frontend in `web/`.

**Tech Stack:** Python 3.12 (subprocess, dataclasses), FastAPI, React 18 + TS + MUI v5 + TanStack Query, pytest, Vitest + MSW.

**Spec:** `docs/superpowers/specs/2026-06-01-verify-diagnostics-design.md`

**Conventions:** Python tests via `.venv/bin/pytest`. Frontend from `web/`: `npm test -- --run`, `npx tsc -b`. tsconfig has `strict` + `noUncheckedIndexedAccess`. Stay on `main`. Commit per task.

---

## Task 1: Classifier in `verify.py`

**Files:**
- Modify: `abench/verify.py`
- Test: `tests/test_verify.py` (append; create if absent)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_verify.py` (if creating, add `from abench import verify` + `from abench.verify import VerifyResult` at top):
```python
from unittest import mock

from abench import verify


def _run(stdout="", stderr="", returncode=0, command="mvn test", raises=None):
    """Run verify.run_verify with subprocess.run mocked to a canned result."""
    if raises is not None:
        with mock.patch("abench.verify.subprocess.run", side_effect=raises):
            return verify.run_verify(".", command, timeout_s=60)
    completed = mock.Mock(stdout=stdout, stderr=stderr, returncode=returncode)
    with mock.patch("abench.verify.subprocess.run", return_value=completed):
        return verify.run_verify(".", command, timeout_s=60)


def test_tests_failed_with_counts():
    out = "Tests run: 10, Failures: 2, Errors: 0\nFailed tests:\n  com.x.AT.tb\n  com.x.AT.tc\n"
    r = _run(stdout=out, returncode=1, command="mvn test")
    assert r.status == "failed"
    assert r.reason == "tests_failed"
    assert r.passed_count == 8 and r.failed_count == 2
    assert "2 of 10" in r.message


def test_passed():
    r = _run(stdout="Tests run: 5, Failures: 0, Errors: 0\n", returncode=0, command="mvn test")
    assert r.status == "passed"
    assert r.reason == "passed"
    assert r.passed_count == 5 and r.failed_count == 0


def test_build_failed_when_no_summary_and_nonzero_exit():
    out = "[INFO] ...\n[ERROR] COMPILATION ERROR :\n[ERROR] Score.java:[10,5] cannot find symbol\nBUILD FAILURE\n"
    r = _run(stdout=out, returncode=1, command="mvn test")
    assert r.status == "error"
    assert r.reason == "build_failed"
    assert "COMPILATION ERROR" in r.message or "build failed" in r.message


def test_tool_not_found_via_exit_127():
    r = _run(stderr="mvn: command not found", returncode=127, command="mvn test")
    assert r.status == "error"
    assert r.reason == "tool_not_found"
    assert "mvn" in r.message


def test_no_tests_run():
    r = _run(stdout="Tests run: 0, Failures: 0, Errors: 0\n", returncode=0, command="mvn test")
    assert r.status == "error"
    assert r.reason == "no_tests"


def test_unparseable_zero_exit():
    r = _run(stdout="some custom output, no summary", returncode=0, command="bash run.sh")
    assert r.status == "error"
    assert r.reason == "unparseable"


def test_timeout():
    import subprocess
    r = _run(command="mvn test", raises=subprocess.TimeoutExpired(cmd="mvn test", timeout=60))
    assert r.status == "timeout"
    assert r.reason == "timeout"


def test_raw_output_is_full_not_truncated():
    big = "x" * 20000 + "\nTests run: 1, Failures: 0, Errors: 0\n"
    r = _run(stdout=big, returncode=0, command="mvn test")
    assert len(r.raw_output) >= 20000  # not truncated to 8000
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_verify.py -v`
Expected: FAIL — `VerifyResult` has no `reason`/`message`; classification not implemented.

- [ ] **Step 3: Rewrite `VerifyResult` + `run_verify` + add helpers**

In `abench/verify.py`, replace the `VerifyResult` dataclass and `run_verify`, and add the two helpers. The new `VerifyResult`:
```python
@dataclass
class VerifyResult:
    status: Status
    reason: str = "skipped"   # passed|tests_failed|build_failed|tool_not_found|no_tests|timeout|unparseable|skipped
    message: str = ""
    command: str | None = None
    duration_s: float | None = None
    passed_count: int | None = None
    failed_count: int | None = None
    failed_names: list[str] = field(default_factory=list)
    raw_output: str = ""      # FULL combined stdout+stderr (the log file needs all of it)
```
Add these helpers above `run_verify`:
```python
_BUILD_MARKERS = (
    "COMPILATION ERROR",
    "BUILD FAILURE",
    "FAILURE: Build failed",
    "cannot find symbol",
    "errors during collection",
    "collected 0 items",
    "error:",
)


def _build_fail_message(output: str, returncode: int) -> str:
    for marker in _BUILD_MARKERS:
        idx = output.find(marker)
        if idx != -1:
            line = output[idx:].splitlines()[0].strip()
            return f"build failed — {line[:160]}"
    return f"build/command failed before tests ran (exit {returncode})"


def _tool_missing(output: str, returncode: int, tool: str) -> bool:
    low = output.lower()
    t = tool.lower()
    return (
        returncode == 127
        or f"{t}: command not found" in low
        or f"{t}: not found" in low
        or (f"{t}: " in low and "not found" in low)
    )
```
Replace `run_verify` with:
```python
def run_verify(workdir: Path, command: str, timeout_s: int) -> VerifyResult:
    """Run `command` from `workdir`, classify the outcome, keep the full output."""
    workdir = Path(workdir)
    started = time.time()
    parts = command.split()
    tool = parts[0] if parts else command
    try:
        completed = subprocess.run(
            command, shell=True, cwd=workdir,
            capture_output=True, text=True, timeout=timeout_s,
        )
    except subprocess.TimeoutExpired:
        return VerifyResult(
            status="timeout", reason="timeout",
            message=f"verify timed out after {timeout_s}s",
            command=command, duration_s=time.time() - started,
        )
    except FileNotFoundError as exc:
        return VerifyResult(
            status="error", reason="tool_not_found",
            message=f"{tool} not found on PATH",
            command=command, duration_s=time.time() - started, raw_output=str(exc),
        )

    output = (completed.stdout or "") + "\n" + (completed.stderr or "")
    duration = time.time() - started
    rc = completed.returncode

    if _tool_missing(output, rc, tool):
        return VerifyResult(
            status="error", reason="tool_not_found",
            message=f"{tool} not found on PATH",
            command=command, duration_s=duration, raw_output=output,
        )

    parser = _parser_for(command)
    parsed: tuple[int, int, list[str]] | None = None
    if parser is not None:
        try:
            parsed = parser(output)
        except ValueError:
            parsed = None

    if parsed is not None:
        passed, failed, names = parsed
        total = passed + failed
        if failed > 0:
            return VerifyResult(
                status="failed", reason="tests_failed",
                message=f"{failed} of {total} tests failed",
                command=command, duration_s=duration,
                passed_count=passed, failed_count=failed, failed_names=names,
                raw_output=output,
            )
        if total == 0:
            return VerifyResult(
                status="error", reason="no_tests", message="no tests were run",
                command=command, duration_s=duration,
                passed_count=0, failed_count=0, raw_output=output,
            )
        if rc == 0:
            return VerifyResult(
                status="passed", reason="passed",
                message=f"{passed} tests passed",
                command=command, duration_s=duration,
                passed_count=passed, failed_count=0, raw_output=output,
            )
        # parsed, no failures, but non-zero exit → something failed around the tests
        return VerifyResult(
            status="error", reason="build_failed",
            message=_build_fail_message(output, rc),
            command=command, duration_s=duration,
            passed_count=passed, failed_count=0, raw_output=output,
        )

    # Unparseable (no parser, or parser raised)
    if rc != 0:
        return VerifyResult(
            status="error", reason="build_failed",
            message=_build_fail_message(output, rc),
            command=command, duration_s=duration, raw_output=output,
        )
    return VerifyResult(
        status="error", reason="unparseable",
        message="could not parse test output",
        command=command, duration_s=duration, raw_output=output,
    )
```
Keep the existing imports, `Status`, `detect_command`, `_PARSER_BY_PREFIX`, `_parser_for`. Ensure `field` is imported from `dataclasses` (it already is).

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_verify.py -v`
Expected: all PASS (8 tests).

- [ ] **Step 5: Commit**

```bash
git add abench/verify.py tests/test_verify.py
git commit -m "feat(verify): classify failures with reason + message; keep full output"
```

---

## Task 2: Propagate `verify_reason`/`verify_message` through Trace + metrics

**Files:**
- Modify: `abench/trace_model.py` (add two fields)
- Modify: `abench/metrics.py` (emit them)
- Test: `tests/test_metrics.py` (append; create if absent)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_metrics.py`:
```python
from abench.metrics import extract, MetricsConfig
from abench.trace_model import Trace


def test_metrics_include_verify_reason_and_message():
    tr = Trace()
    tr.verify_status = "error"
    tr.verify_reason = "build_failed"
    tr.verify_message = "build failed — COMPILATION ERROR"
    m = extract(tr, "", MetricsConfig())
    assert m["verify_reason"] == "build_failed"
    assert m["verify_message"] == "build failed — COMPILATION ERROR"
    assert m["success"] is None  # error → success None (unchanged)
```
(If `MetricsConfig()` requires args, mirror the construction used by existing tests in `tests/test_metrics.py`.)

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_metrics.py -k verify_reason -v`
Expected: FAIL — `Trace` has no `verify_reason`; key missing.

- [ ] **Step 3: Add Trace fields**

In `abench/trace_model.py`, in the `Trace` dataclass, after the existing
`verify_failed_names` / `verify_baseline_unknown` fields, add:
```python
    verify_reason: str | None = None
    verify_message: str | None = None
```
(Place them among the other `verify_*` fields; defaults make them optional so
`trace_from_dict(**remaining)` still works for older trace.json without these keys.)

- [ ] **Step 4: Emit in metrics**

In `abench/metrics.py`, in the returned dict, after `"verify_failed_names": ...,`
add:
```python
        "verify_reason": trace.verify_reason,
        "verify_message": trace.verify_message,
```

- [ ] **Step 5: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_metrics.py -k verify_reason -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add abench/trace_model.py abench/metrics.py tests/test_metrics.py
git commit -m "feat(verify): propagate verify_reason/verify_message via Trace + metrics"
```

---

## Task 3: Runner writes `verify_output.log` + baseline log; sets trace reason/message

**Files:**
- Modify: `abench/runner.py` (`_run_one` verify block + `_maybe_run_baseline_verify`)
- Test: `tests/test_runner_verify_log.py` (create)

- [ ] **Step 1: Write the failing test**

`tests/test_runner_verify_log.py`:
```python
from pathlib import Path
from unittest import mock

from abench import runner
from abench.verify import VerifyResult


def test_run_one_writes_verify_output_log(tmp_path: Path, monkeypatch):
    rundir = tmp_path / "rundir"
    rundir.mkdir()

    vr = VerifyResult(
        status="error", reason="build_failed",
        message="build failed — COMPILATION ERROR",
        command="mvn test", duration_s=12.3,
        passed_count=0, failed_count=0, raw_output="LOTS OF OUTPUT\nBUILD FAILURE\n",
    )
    monkeypatch.setattr(runner, "run_verify", lambda *a, **k: vr)

    runner._write_verify_log(rundir, vr)

    log = (rundir / "verify_output.log").read_text()
    assert "# command: mvn test" in log
    assert "build_failed" in log
    assert "BUILD FAILURE" in log
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_runner_verify_log.py -v`
Expected: FAIL — `runner._write_verify_log` does not exist.

- [ ] **Step 3: Add the log writer + wire it into `_run_one` and the baseline**

In `abench/runner.py`, add a module-level helper:
```python
def _write_verify_log(rundir: Path, v) -> None:
    """Persist the full verify output with a small diagnostic header."""
    dur = f"{v.duration_s:.1f}s" if v.duration_s is not None else "—"
    header = (
        f"# command: {v.command}\n"
        f"# status: {v.status} ({v.reason})\n"
        f"# message: {v.message}\n"
        f"# duration: {dur}\n"
        f"───\n"
    )
    (Path(rundir) / "verify_output.log").write_text(header + (v.raw_output or ""))
```
In `_run_one`, inside the `try:` of the verify block, after the existing
`result.trace.verify_failed_names = v.failed_names` line, add:
```python
                    result.trace.verify_reason = v.reason
                    result.trace.verify_message = v.message
                    _write_verify_log(rundir, v)
```
And in the `except Exception as exc:` branch of that block (which currently sets
`verify_status = "error"`), also set:
```python
                    result.trace.verify_reason = "unparseable"
                    result.trace.verify_message = f"verify raised unexpectedly: {exc!r}"
```
In `_maybe_run_baseline_verify`, replace the `cache_path.write_text(json.dumps({...}))`
call so it also records reason/message and writes a baseline log next to the cache:
```python
        v = run_verify(workdir, command, exp.verify.timeout_s)
        cache_path.write_text(json.dumps({
            "command": command, "reference_sha": ref_sha,
            "status": v.status, "reason": v.reason, "message": v.message,
            "passed_count": v.passed_count, "failed_count": v.failed_count,
        }))
        _write_verify_log(cache_path.parent, v)
        # name the baseline log distinctly so it doesn't collide with a run log
        (cache_path.parent / "verify_output.log").rename(
            cache_path.parent / ".verify-baseline-output.log")
```
(The `rename` keeps `_write_verify_log` DRY — it always writes `verify_output.log`,
then the baseline path renames it to `.verify-baseline-output.log`.)

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/pytest tests/test_runner_verify_log.py -v`
Expected: PASS.

- [ ] **Step 5: Run the verify + runner tests together (no regressions)**

Run: `.venv/bin/pytest tests/test_verify.py tests/test_metrics.py tests/test_runner_verify_log.py -q`
Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add abench/runner.py tests/test_runner_verify_log.py
git commit -m "feat(verify): write verify_output.log (run + baseline) and set trace reason/message"
```

---

## Task 4: API endpoints — `/verify_log` and `/experiments/{name}/verify_command`

**Files:**
- Modify: `abench_ui/server.py`
- Test: `tests/abench_ui/test_verify_api.py` (create)

- [ ] **Step 1: Write the failing tests**

`tests/abench_ui/test_verify_api.py`:
```python
import json
from pathlib import Path

from fastapi.testclient import TestClient

from abench_ui.server import create_app


def _seed(exp_dir: Path, name: str, condition: str, rep: int):
    d = exp_dir / name / "runs" / name / condition / f"rep_{rep}"
    d.mkdir(parents=True, exist_ok=True)
    (d / "verify_output.log").write_text("# command: mvn test\n───\nBUILD FAILURE\n")


def test_verify_log_served(tmp_path: Path):
    exp_dir = tmp_path / "experiments"
    _seed(exp_dir, "exp", "baseline", 0)
    client = TestClient(create_app(experiments_dir=exp_dir))
    resp = client.get("/api/runs/exp/baseline/0/verify_log")
    assert resp.status_code == 200
    assert "BUILD FAILURE" in resp.text


def test_verify_log_404_when_absent(tmp_path: Path):
    exp_dir = tmp_path / "experiments"
    (exp_dir / "exp" / "runs" / "exp" / "baseline" / "rep_0").mkdir(parents=True)
    client = TestClient(create_app(experiments_dir=exp_dir))
    resp = client.get("/api/runs/exp/baseline/0/verify_log")
    assert resp.status_code == 404


def test_detect_verify_command_maven(tmp_path: Path):
    exp_dir = tmp_path / "experiments"
    d = exp_dir / "exp"
    (d / "stripped").mkdir(parents=True)
    (d / "stripped" / "pom.xml").write_text("<project/>")
    (d / "reference").mkdir()
    (d / "reference" / "pom.xml").write_text("<project/>")
    (d / "prompts").mkdir()
    (d / "prompts" / "task.md").write_text("do it")
    (d / "prompts" / "system.md").write_text("sys")
    (d / "experiment.yaml").write_text(
        "name: exp\nfixture_path: ./stripped\nreference_path: ./reference\n"
        "task_prompt: ./prompts/task.md\nsystem_prompt: ./prompts/system.md\n"
        "model: m\nrepetitions: 1\noutput_dir: ./runs\n"
        "conditions:\n  - {name: baseline, augmentation: null}\n"
    )
    client = TestClient(create_app(experiments_dir=exp_dir))
    resp = client.get("/api/experiments/exp/verify_command")
    assert resp.status_code == 200
    body = resp.json()
    assert body["system"] == "maven"
    assert body["command"] == "mvn test"


def test_detect_verify_command_null_when_unresolvable(tmp_path: Path):
    exp_dir = tmp_path / "experiments"
    (exp_dir / "exp").mkdir(parents=True)
    client = TestClient(create_app(experiments_dir=exp_dir))
    resp = client.get("/api/experiments/exp/verify_command")
    # no experiment.yaml → 404; a present-but-unresolvable fixture → {command:null}
    assert resp.status_code == 404
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/abench_ui/test_verify_api.py -v`
Expected: FAIL — routes not registered.

- [ ] **Step 3: Add the routes + a label helper**

In `abench_ui/server.py`, add a module-level helper near the top (after imports):
```python
def _verify_system_label(command: str | None) -> str | None:
    if not command:
        return None
    first = command.split()[0]
    if first in ("mvn", "./mvnw"):
        return "maven"
    if first in ("gradle", "./gradlew"):
        return "gradle"
    if first == "pytest":
        return "pytest"
    return "custom"
```
Add the `/verify_log` route immediately after the existing `/events` route
(`@api.get("/runs/{name}/{condition}/{rep}/events")`):
```python
    @api.get("/runs/{name}/{condition}/{rep}/verify_log")
    def _read_verify_log(name: str, condition: str, rep: int):
        runs_dir = _exp_dir_for(name) / "runs" / name
        try:
            return Response(
                runs_mod.read_artefact(runs_dir, condition, rep, "verify_output.log"),
                media_type="text/plain",
            )
        except runs_mod.RunNotFound as exc:
            raise HTTPException(404, str(exc))
```
Add the detect route after `@api.get("/experiments/{name}")`:
```python
    @api.get("/experiments/{name}/verify_command")
    def _detect_verify_command(name: str):
        from abench.config import load_experiment
        from abench.verify import detect_command

        exp_dir = _exp_dir_for(name)
        yaml_path = exp_dir / "experiment.yaml"
        if not yaml_path.is_file():
            raise HTTPException(404, f"experiment '{name}' not found")
        try:
            exp = load_experiment(yaml_path)
            command = exp.verify.command or detect_command(exp.fixture_path)
        except Exception:
            # fixture not populated / invalid → can't detect yet
            command = None
        return {"command": command, "system": _verify_system_label(command)}
```
(`Response` and `HTTPException` are already imported in server.py.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/abench_ui/test_verify_api.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Full Python suite (no regressions)**

Run: `.venv/bin/pytest -q --deselect tests/test_run_e2e.py::test_abench_run_e2e --deselect tests/test_opencode_client_integration.py::test_real_client_runs_trivial_task`
Expected: green (the two deselected are env-dependent real-opencode tests, pre-existing).

- [ ] **Step 6: Commit**

```bash
git add abench_ui/server.py tests/abench_ui/test_verify_api.py
git commit -m "feat(ui/server): /verify_log + /experiments/{name}/verify_command endpoints"
```

---

## Task 5: Frontend — types, hooks, build-system label

**Files:**
- Modify: `web/src/api/types.ts` (add `verify_reason`/`verify_message`; `DetectedVerify`)
- Modify: `web/src/api/queries.ts` (`useVerifyLog`, `useDetectedVerify`)
- Create: `web/src/lib/buildSystem.ts`

- [ ] **Step 1: Extend types**

In `web/src/api/types.ts`, add `verify_reason?: string | null;` and
`verify_message?: string | null;` to BOTH the `Trace` interface and the `MetricsJson`
interface (alongside the other `verify_*` fields). Then add:
```ts
export interface DetectedVerify {
  command: string | null;
  system: "maven" | "gradle" | "pytest" | "custom" | null;
}
```

- [ ] **Step 2: Add the build-system label helper**

`web/src/lib/buildSystem.ts`:
```ts
// Human label for a verify command's build system (frontend-derived, post-run).
export function buildSystemLabel(command: string | null | undefined): string {
  if (!command) return "—";
  const first = command.split(" ")[0] ?? "";
  if (first === "mvn" || first === "./mvnw") return "Maven";
  if (first === "gradle" || first === "./gradlew") return "Gradle";
  if (first === "pytest") return "pytest";
  return "custom";
}
```

- [ ] **Step 3: Add hooks**

In `web/src/api/queries.ts`, add query keys to `qk`:
```ts
  verifyLog: (name: string, condition: string, rep: number) =>
    ["verifyLog", name, condition, rep] as const,
  detectedVerify: (name: string) => ["detectedVerify", name] as const,
```
Add the hooks (after `usePatch`):
```ts
export const useVerifyLog = (
  name: string, condition: string, rep: number, enabled: boolean,
) =>
  useQuery({
    queryKey: qk.verifyLog(name, condition, rep),
    enabled,
    queryFn: () => apiGet<string>(`/api/runs/${name}/${condition}/${rep}/verify_log`),
  });

export const useDetectedVerify = (name: string | undefined) =>
  useQuery({
    queryKey: qk.detectedVerify(name ?? ""),
    enabled: Boolean(name),
    queryFn: () => apiGet<t.DetectedVerify>(`/api/experiments/${name}/verify_command`),
  });
```

- [ ] **Step 4: Typecheck**

Run (from `web/`): `npx tsc -b`
Expected: clean (no consumers yet).

- [ ] **Step 5: Commit**

```bash
git add web/src/api/types.ts web/src/api/queries.ts web/src/lib/buildSystem.ts
git commit -m "feat(ui/web): verify reason/message types + verify-log/detect hooks"
```

---

## Task 6: Frontend — VerifyCard with reason, build system, and log viewer

**Files:**
- Modify: `web/src/components/VerifyCard.tsx`
- Test: `web/tests/VerifyCard.test.tsx` (extend the existing file)

- [ ] **Step 1: Rewrite `VerifyCard`**

Replace `web/src/components/VerifyCard.tsx` with:
```tsx
import { useState } from "react";
import {
  Card, CardContent, Stack, Typography, Chip, Button, Collapse, Box, Dialog,
  DialogTitle, DialogContent, CircularProgress,
} from "@mui/material";
import { alpha } from "@mui/material/styles";
import { useVerifyLog } from "../api/queries";
import { buildSystemLabel } from "../lib/buildSystem";
import { selectable } from "../theme";
import type { Trace } from "../api/types";

interface Props {
  trace: Trace;
  name: string;
  condition: string;
  rep: number;
}

export default function VerifyCard({ trace, name, condition, rep }: Props) {
  const [open, setOpen] = useState(false);
  const [logOpen, setLogOpen] = useState(false);
  const log = useVerifyLog(name, condition, rep, logOpen);

  const status = trace.verify_status;
  if (!status) return null;
  const passed = trace.verify_passed_count ?? 0;
  const failed = trace.verify_failed_count ?? 0;
  const total = passed + failed;
  const toneColor: "success" | "error" | "warning" =
    status === "passed" ? "success" : status === "failed" ? "error" : "warning";
  const headline = trace.verify_message || status;

  return (
    <Card
      variant="outlined"
      sx={{
        bgcolor: (th) => alpha(th.palette[toneColor].main, th.palette.mode === "dark" ? 0.18 : 0.1),
        borderColor: (th) => alpha(th.palette[toneColor].main, 0.4),
      }}
    >
      <CardContent>
        <Stack direction="row" alignItems="center" spacing={1} flexWrap="wrap">
          <Chip size="small" label={`🧪 ${status}`} />
          {trace.verify_reason && trace.verify_reason !== status && (
            <Chip size="small" variant="outlined" label={trace.verify_reason} />
          )}
          <Typography variant="body2">{headline}</Typography>
          <Box sx={{ flexGrow: 1 }} />
          <Button size="small" onClick={() => setLogOpen(true)}>View verify output</Button>
        </Stack>

        <Typography variant="caption" color="text.secondary" sx={{ display: "block", mt: 0.5 }}>
          {buildSystemLabel(trace.verify_command)} · <code>{trace.verify_command ?? "—"}</code>
          {total > 0 && <> · {passed}/{total} passed</>}
          {trace.verify_duration_s != null && <> · {trace.verify_duration_s.toFixed(1)}s</>}
        </Typography>

        {trace.verify_failed_names.length > 0 && (
          <>
            <Button size="small" onClick={() => setOpen(!open)} sx={{ mt: 1 }}>
              {open ? "hide failing ▴" : `show ${trace.verify_failed_names.length} failing ▾`}
            </Button>
            <Collapse in={open}>
              <Box sx={{ mt: 1, fontFamily: "monospace", fontSize: 12, ...selectable }}>
                {trace.verify_failed_names.map((n) => (
                  <Typography key={n} variant="body2" color="error">— {n}</Typography>
                ))}
              </Box>
            </Collapse>
          </>
        )}

        <Dialog open={logOpen} onClose={() => setLogOpen(false)} maxWidth="md" fullWidth>
          <DialogTitle>verify_output.log</DialogTitle>
          <DialogContent>
            {log.isLoading && <CircularProgress size={20} />}
            {log.error && <Typography color="error">No verify log for this run.</Typography>}
            {log.data != null && (
              <Box
                component="pre"
                sx={{
                  m: 0, whiteSpace: "pre-wrap", fontFamily: "monospace", fontSize: 12,
                  bgcolor: "#0e1116", color: "#dbe1ec", borderRadius: 1, p: 1.5,
                  maxHeight: 480, overflow: "auto", userSelect: "text",
                }}
              >
                {log.data}
              </Box>
            )}
          </DialogContent>
        </Dialog>
      </CardContent>
    </Card>
  );
}
```
NOTE: `VerifyCard` now needs `name`/`condition`/`rep` props — TraceView passes them (Task 7).

- [ ] **Step 2: Update the existing VerifyCard test**

The existing `web/tests/VerifyCard.test.tsx` renders `<VerifyCard trace={...} />` with
no QueryClient. Replace it with a version that supplies the new props + a QueryClient
and MSW, and asserts the message + log viewer:
```tsx
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { http, HttpResponse } from "msw";
import { expect, test } from "vitest";
import { mswServer } from "./setup";
import VerifyCard from "../src/components/VerifyCard";
import type { Trace } from "../src/api/types";

const base: Trace = {
  turns: [], verify_status: "error", verify_command: "mvn test",
  verify_duration_s: 12.3, verify_passed_count: 0, verify_failed_count: 0,
  verify_failed_names: [], verify_baseline_unknown: false,
  isolation_nonce: null, final_diff_summary: null,
  verify_reason: "build_failed", verify_message: "build failed — COMPILATION ERROR",
};

function wrap(ui: React.ReactNode) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={qc}>{ui}</QueryClientProvider>;
}

test("shows reason, message, build system; opens the log dialog", async () => {
  mswServer.use(http.get("/api/runs/exp/baseline/0/verify_log", () =>
    new HttpResponse("# command: mvn test\n───\nBUILD FAILURE\n", {
      headers: { "content-type": "text/plain" },
    })));
  render(wrap(<VerifyCard trace={base} name="exp" condition="baseline" rep={0} />));
  expect(screen.getByText(/build failed — COMPILATION ERROR/)).toBeInTheDocument();
  expect(screen.getByText("build_failed")).toBeInTheDocument();
  expect(screen.getByText(/Maven/)).toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: /view verify output/i }));
  expect(await screen.findByText(/BUILD FAILURE/)).toBeInTheDocument();
});

test("renders nothing when verify_status is null", () => {
  const { container } = render(
    wrap(<VerifyCard trace={{ ...base, verify_status: null }} name="exp" condition="baseline" rep={0} />),
  );
  expect(container.firstChild).toBeNull();
});
```

- [ ] **Step 2b: Run test to verify it fails**

Run: `npm test -- --run tests/VerifyCard.test.tsx`
Expected: FAIL (component not updated / props mismatch) before Step 1 is applied;
after Step 1 it should pass. (If you applied Step 1 first, this is the green run.)

- [ ] **Step 3: Run test to verify it passes + typecheck**

Run: `npm test -- --run tests/VerifyCard.test.tsx` → PASS.
Run: `npx tsc -b` → clean (TraceView passes the new props in Task 7; if tsc flags the
TraceView call site now, that's fixed in Task 7 — you may run tsc after Task 7).

- [ ] **Step 4: Commit**

```bash
git add web/src/components/VerifyCard.tsx web/tests/VerifyCard.test.tsx
git commit -m "feat(ui/web): VerifyCard shows reason/message, build system, log viewer"
```

---

## Task 7: Frontend — wire VerifyCard props, VerdictBanner message, baseline warning, build-system display

**Files:**
- Modify: `web/src/pages/TraceView.tsx` (pass props to VerifyCard; render baseline warning)
- Modify: `web/src/components/VerdictBanner.tsx` (error branch shows message)
- Modify: `web/src/components/FixturesPanel.tsx` (build-system row)
- Modify: `web/src/pages/ExperimentEdit.tsx` (fetch detect, pass to FixturesPanel)
- Modify: `web/src/pages/ExperimentResults.tsx` (baseline chip — optional, see step)

- [ ] **Step 1: VerdictBanner — surface the message on error**

In `web/src/components/VerdictBanner.tsx`, replace the `error` branch:
```tsx
  if (v === "error") {
    return (
      <Alert severity="warning">
        <Typography variant="subtitle1">⚠ Verify error</Typography>
        <Typography variant="caption" color="text.secondary">
          {trace.verify_message ?? "see verify output"}
        </Typography>
      </Alert>
    );
  }
```

- [ ] **Step 2: TraceView — pass props + baseline warning**

In `web/src/pages/TraceView.tsx`:

(a) Replace the `<VerifyCard trace={trace.data} />` call with:
```tsx
        <VerifyCard trace={trace.data} name={name!} condition={condition!} rep={repN} />
```

(b) Add a baseline warning just under the `<VerdictBanner .../>` line:
```tsx
        {trace.data.verify_baseline_unknown && (
          <Alert severity="warning">
            The reference project itself does not pass verify (build/environment issue) —
            run verdicts may be unreliable.
          </Alert>
        )}
```
Add `Alert` to the existing `@mui/material` import in TraceView if not already there
(it imports `Alert` already for the error state — confirm; if present, no change).

- [ ] **Step 3: FixturesPanel — build-system row**

In `web/src/components/FixturesPanel.tsx`, add two optional props and a row. Update the
`Props` interface:
```tsx
interface Props {
  fixturePath?: string;
  referencePath?: string;
  hasFixture: boolean;
  hasReference: boolean;
  verifyCommand?: string | null;
  verifySystem?: string | null;
}
```
And in the component body, after the two existing `<Row .../>` lines, add:
```tsx
          <Stack direction="row" spacing={1} alignItems="center">
            <Typography variant="body2">
              <b>build:</b>{" "}
              {verifyCommand
                ? <>{verifySystem ?? "custom"} · <code>{verifyCommand}</code></>
                : <i>no build system detected — set <code>verify.command</code></i>}
            </Typography>
          </Stack>
```
Update the `export default function FixturesPanel({ ... })` destructuring to include
`verifyCommand, verifySystem`.

- [ ] **Step 4: ExperimentEdit — fetch detected verify, pass to FixturesPanel**

In `web/src/pages/ExperimentEdit.tsx`:
- add `useDetectedVerify` to the `../api/queries` import;
- call it: `const detected = useDetectedVerify(name);`
- pass to the `<FixturesPanel ... />` element:
```tsx
            verifyCommand={detected.data?.command ?? null}
            verifySystem={detected.data?.system ?? null}
```

- [ ] **Step 5: ExperimentResults — baseline chip (lightweight)**

In `web/src/pages/ExperimentResults.tsx`, the per-run table already exists; add a
note above the Runs section when any run reports baseline-unknown is out of scope
for the summary endpoint. Instead, keep it simple: SKIP the Results chip in Phase 1
(the TraceView banner covers it). Do nothing here. (Documented as intentional.)

- [ ] **Step 6: Run the full frontend suite + typecheck**

Run: `npm test -- --run`
Expected: all green (the existing VerdictBanner test asserts `/✗ Verify failed/` for
the `failed` status — unchanged; the `error` branch has no dedicated assertion, so the
reworded error Alert is safe. If a test asserted the old "Verify errored" text, update
it to `/Verify error/`.)
Run: `npx tsc -b` → clean.

- [ ] **Step 7: Commit**

```bash
git add web/src/pages/TraceView.tsx web/src/components/VerdictBanner.tsx \
        web/src/components/FixturesPanel.tsx web/src/pages/ExperimentEdit.tsx
git commit -m "feat(ui/web): verify message in banner, baseline warning, build-system in fixtures"
```

---

## Task 8: Integration — build, both suites, boot smoke

**Files:** none (verification).

- [ ] **Step 1: Frontend suite + typecheck + build**

Run (from `web/`):
```bash
npm test -- --run
npx tsc -b
npm run build
```
Expected: all green; tsc clean; build writes `abench_ui/static/`.

- [ ] **Step 2: Python suite**

Run: `.venv/bin/pytest -q --deselect tests/test_run_e2e.py::test_abench_run_e2e --deselect tests/test_opencode_client_integration.py::test_real_client_runs_trivial_task`
Expected: green.

- [ ] **Step 3: Boot + endpoint smoke**

```bash
.venv/bin/abench-ui --experiments-dir experiments --port 8804 &
sleep 4
curl -s -o /dev/null -w "detect %{http_code}\n" "http://127.0.0.1:8804/api/experiments/picocli-putValue/verify_command"
curl -s "http://127.0.0.1:8804/api/experiments/picocli-putValue/verify_command"; echo
curl -s -o /dev/null -w "verify_log(missing) %{http_code}\n" "http://127.0.0.1:8804/api/runs/picocli-putValue/baseline/0/verify_log"
kill %1
```
Expected: `detect 200` with `{"command": ..., "system": ...}` (command/system may be
null if picocli-putValue's fixture isn't populated — acceptable); `verify_log(missing) 404`.

- [ ] **Step 4: Manual browser smoke (human)**

After `abench-ui` boot, on a run that errored: VerifyCard shows the reason chip +
message + build-system line + a working "View verify output" dialog with the log;
ExperimentEdit's Fixtures panel shows the detected build system; a reference-fails run
shows the baseline warning on TraceView. (If you cannot run a browser, say so — do not
claim visual success.)

- [ ] **Step 5: Final commit (if smoke fixes needed)**

```bash
git add -A && git commit -m "fix(verify): diagnostics smoke fixes"
```
(Skip if nothing changed.)

---

## Self-review notes (for the executor)

- **Status contract unchanged:** `verify_status` stays `{passed,failed,skipped,error,timeout}`;
  `reason` adds granularity to `error`. `metrics.success` still derives only from
  `verify_status` (Task 2 test asserts `error → success None`).
- **Types line up:** `VerifyResult.reason/message` (Task 1) → `Trace.verify_reason/message`
  (Task 2) → metrics keys (Task 2) → frontend `Trace`/`MetricsJson` (Task 5) → VerifyCard
  (Task 6). `DetectedVerify {command, system}` (Task 5) ↔ `/verify_command` endpoint
  (Task 4) ↔ FixturesPanel props (Task 7).
- **VerifyCard prop change** (`name/condition/rep`) ripples to its one caller, TraceView
  (Task 7 step 2a). No other caller (grep `VerifyCard` to confirm).
- **Log file is the single home for full output** — trace.json keeps only the short
  `verify_message`; `_write_verify_log` writes the full `raw_output`.
- **`_write_verify_log` is reused** for both run and baseline (baseline renames the file).
- Frontend `buildSystemLabel` (post-run, from `verify_command`) and the backend
  `_verify_system_label` (pre-run, for the detect endpoint) intentionally duplicate a
  tiny mapping on each side of the wire — acceptable; do not over-abstract across the
  boundary.
