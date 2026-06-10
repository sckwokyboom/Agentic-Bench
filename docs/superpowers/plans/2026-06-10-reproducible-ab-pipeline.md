# Reproducible A/B Pipeline (overlay + GT producer + scripts) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Полный A/B picocli-putValue (4 условия, включая per-session GT-тул `impact`) воспроизводится на чистой машине (macOS/Linux/Windows) парой Python-команд.

**Architecture:** abench получает один generic-механизм — per-condition workdir-overlay с `.tmpl`-подстановкой; Graph-Tipper получает один производящий вход `produce_artifacts` (joern→slice→agent→capture→gen→impact-data→provenance); склейка — `prepare.py` эксперимента. Спека: `docs/superpowers/specs/2026-06-10-reproducible-ab-pipeline-design.md` (читать перед работой).

**Tech Stack:** Python stdlib (никакого bash — Windows), pytest, pydantic (конфиг abench), gradle wrapper (`gradlew`/`gradlew.bat`), Docker (sandbox), Joern (только стадии slice/export).

**Repos:** Ф1, Ф3, Ф4 — `/Users/sckwoky/Projects/Agentic-Bench` (или клон); Ф2 — `/Users/sckwoky/Projects/Graph-Tipper`. Коммиты — в репо текущей фазы, конвенция сообщений — `feat(...)/fix(...)/docs(...)` как в логах обоих репо.

---

## File structure (что создаём/трогаем)

**Agentic-Bench:**
```
abench/config.py                 # +Condition.overlay, +Experiment.overlay_env, валидация
abench/envutil.py                # NEW: expand_env_refs("{env:NAME}") — общий резолвер
abench/fixture.py                # create_workdir(+overlay_dir,+overlay_env), .tmpl-рендер, .impact в excludes
abench/runner.py                 # threading overlay в create_workdir (строка ~225)
abench/prompt.py                 # +1 строка в GROUNDING_GUARD
abench/opencode_client.py        # cache_mounts через expand_env_refs (цикл ~строка 256)
docker/Dockerfile.sandbox        # +python3
tests/test_config_overlay.py     # NEW
tests/test_fixture_overlay.py    # NEW
tests/test_envutil.py            # NEW
tests/test_prompt.py             # + тест guard-строки (файл существует — дописать)
scripts/setup_check.py           # NEW (Ф3)
experiments/picocli-putValue/
  prepare.py fixture.lock strip_target.py tests/test_strip_target.py   # NEW (Ф3)
  overlays/impact/.opencode/impact.json.tmpl                            # NEW (Ф3)
  slices/impact-tool-briefing.md REPRODUCE.md                           # NEW (Ф3)
  experiment.yaml                                                       # 4 условия + sandbox
.gitignore                       # + overlays/impact/.impact/, overlays/impact/.opencode/tools/
```

**Graph-Tipper:**
```
tools/get_joern.py tools/joern.version       # NEW
harness/impact/produce_artifacts.py          # NEW: стадии + CLI
harness/tests/impact/test_get_joern.py       # NEW
harness/tests/impact/test_produce_artifacts.py  # NEW
```

---

## Ф1 — abench: per-condition overlay

### Task 1: Конфиг — `Condition.overlay`, `Experiment.overlay_env`

**Files:** Modify: `abench/config.py` · Create: `tests/test_config_overlay.py`

- [ ] **Step 1.1: failing test**

```python
# tests/test_config_overlay.py
import pytest
import yaml
from abench.config import load_experiment

BASE = {
    "name": "t", "fixture_path": "./fx", "reference_path": "./ref",
    "task_prompt": "do", "system_prompt": "sys", "model": "m",
    "output_dir": "./runs",
    "conditions": [{"name": "baseline", "augmentation": None}],
}

def _write(tmp_path, data):
    (tmp_path / "fx").mkdir(exist_ok=True)
    (tmp_path / "ref").mkdir(exist_ok=True)
    p = tmp_path / "experiment.yaml"
    p.write_text(yaml.safe_dump(data))
    return p

def test_overlay_resolved_relative_to_yaml_and_validated(tmp_path):
    (tmp_path / "ov").mkdir()
    data = dict(BASE)
    data["conditions"] = [{"name": "aug", "augmentation": None, "overlay": "./ov"}]
    exp = load_experiment(_write(tmp_path, data))
    assert exp.conditions[0].overlay == str((tmp_path / "ov").resolve())

def test_missing_overlay_dir_fails_at_load(tmp_path):
    data = dict(BASE)
    data["conditions"] = [{"name": "aug", "augmentation": None, "overlay": "./nope"}]
    with pytest.raises(ValueError, match="overlay"):
        load_experiment(_write(tmp_path, data))

def test_overlay_env_defaults_empty(tmp_path):
    exp = load_experiment(_write(tmp_path, dict(BASE)))
    assert exp.overlay_env == {}
```

- [ ] **Step 1.2:** Run: `.venv/bin/pytest tests/test_config_overlay.py -q` — Expected: FAIL (`overlay` неизвестное поле / нет атрибута).

- [ ] **Step 1.3: минимальная имплементация.** В `abench/config.py`:

В `Condition` добавить поле (после `augmentation`):
```python
    overlay: str | None = Field(
        default=None,
        title="Overlay",
        description=(
            "Directory copied into the run workdir before the seed commit "
            "(per-session tool files); blank = none. '*.tmpl' files are "
            "rendered with overlay_env and written without the suffix."
        ),
    )
```

В `Experiment` добавить (рядом с `isolation`):
```python
    overlay_env: dict[str, str] = Field(
        default_factory=dict,
        title="Overlay env",
        description=(
            "Variables substituted into overlay '*.tmpl' files as ${NAME}. "
            "Values may use the '{env:NAME}' indirection, resolved from the "
            "process environment at run start."
        ),
    )
```

В `load_experiment` после цикла augmentation-резолва:
```python
    for cond in data.get("conditions", []):
        if cond.get("overlay"):
            cond["overlay"] = str((base / cond["overlay"]).resolve())
```

В `_validate` (в конец):
```python
    for cond in exp.conditions:
        if cond.overlay is not None and not Path(cond.overlay).is_dir():
            raise ValueError(f"overlay dir not found: {cond.overlay} (condition {cond.name})")
```

- [ ] **Step 1.4:** Run: `.venv/bin/pytest tests/test_config_overlay.py -q` — Expected: 3 passed.
- [ ] **Step 1.5:** Commit: `git add abench/config.py tests/test_config_overlay.py && git commit -m "feat(config): per-condition overlay dir + experiment overlay_env"`

### Task 2: `envutil.expand_env_refs`

**Files:** Create: `abench/envutil.py`, `tests/test_envutil.py`

- [ ] **Step 2.1: failing test**

```python
# tests/test_envutil.py
import pytest
from abench.envutil import expand_env_refs

def test_expands_env_ref(monkeypatch):
    monkeypatch.setenv("GT_HOME", "/opt/gt")
    assert expand_env_refs("{env:GT_HOME}:/mnt:ro") == "/opt/gt:/mnt:ro"

def test_plain_string_untouched():
    assert expand_env_refs("/a/b:/c") == "/a/b:/c"

def test_missing_env_raises(monkeypatch):
    monkeypatch.delenv("NOPE_VAR", raising=False)
    with pytest.raises(ValueError, match="NOPE_VAR"):
        expand_env_refs("{env:NOPE_VAR}/x")
```

- [ ] **Step 2.2:** Run: `.venv/bin/pytest tests/test_envutil.py -q` — Expected: FAIL (module not found).
- [ ] **Step 2.3: имплементация**

```python
# abench/envutil.py
"""'{env:NAME}' indirection shared by sandbox cache_mounts and overlay_env."""
from __future__ import annotations

import os
import re

_ENV_REF = re.compile(r"\{env:([A-Za-z_][A-Za-z0-9_]*)\}")


def expand_env_refs(value: str) -> str:
    def sub(m: re.Match) -> str:
        name = m.group(1)
        if name not in os.environ:
            raise ValueError(
                f"environment variable {name} referenced as {{env:{name}}} is not set")
        return os.environ[name]
    return _ENV_REF.sub(sub, value)
```

- [ ] **Step 2.4:** Run: `.venv/bin/pytest tests/test_envutil.py -q` — Expected: 3 passed.
- [ ] **Step 2.5:** Commit: `git add abench/envutil.py tests/test_envutil.py && git commit -m "feat(envutil): shared {env:NAME} expansion"`

### Task 3: fixture — overlay-копия, `.tmpl`-рендер, `.impact` вне диффа

**Files:** Modify: `abench/fixture.py` · Create: `tests/test_fixture_overlay.py`

- [ ] **Step 3.1: failing test**

```python
# tests/test_fixture_overlay.py
import subprocess
import pytest
from abench import fixture as fx

def _mkfixture(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    (src / "Main.java").write_text("class Main {}\n")
    return src

def _mkoverlay(tmp_path):
    ov = tmp_path / "ov"
    (ov / ".opencode" / "tools").mkdir(parents=True)
    (ov / ".opencode" / "tools" / "impact.ts").write_text('const s = `${x}`;\n')  # literal ${} survives
    (ov / ".opencode" / "impact.json.tmpl").write_text('{"harness_path": "${GT_HOME}"}\n')
    return ov

def test_overlay_copied_rendered_and_seed_committed(tmp_path):
    src, ov = _mkfixture(tmp_path), _mkoverlay(tmp_path)
    wd, _sha = fx.create_workdir(src, overlay_dir=ov, overlay_env={"GT_HOME": "/opt/gt"})
    try:
        assert (wd / ".opencode" / "impact.json").read_text() == '{"harness_path": "/opt/gt"}\n'
        assert not (wd / ".opencode" / "impact.json.tmpl").exists()
        assert (wd / ".opencode" / "tools" / "impact.ts").read_text() == 'const s = `${x}`;\n'
        tracked = subprocess.run(["git", "ls-tree", "-r", "--name-only", "HEAD"],
                                 cwd=wd, capture_output=True, text=True).stdout
        assert ".opencode/impact.json" in tracked          # seed commit includes overlay
        assert fx.diff_workdir(wd) == ""                   # overlay is not "agent changes"
    finally:
        fx.cleanup(wd)

def test_unknown_tmpl_var_raises_with_names(tmp_path):
    src, ov = _mkfixture(tmp_path), _mkoverlay(tmp_path)
    with pytest.raises(RuntimeError, match=r"impact\.json\.tmpl.*GT_HOME"):
        fx.create_workdir(src, overlay_dir=ov, overlay_env={})

def test_impact_dir_excluded_from_diff(tmp_path):
    src = _mkfixture(tmp_path)
    wd, _ = fx.create_workdir(src)
    try:
        (wd / ".impact").mkdir()
        (wd / ".impact" / "cache.json").write_text("{}")
        assert fx.diff_workdir(wd) == ""
        assert fx.made_source_changes(wd) is False
    finally:
        fx.cleanup(wd)
```

- [ ] **Step 3.2:** Run: `.venv/bin/pytest tests/test_fixture_overlay.py -q` — Expected: FAIL (`create_workdir() got an unexpected keyword argument`).
- [ ] **Step 3.3: имплементация.** В `abench/fixture.py`:

Константа рядом с `OPENCODE_ARTIFACTS`:
```python
# Tool runtime caches written into the workdir mid-session (e.g. the GT impact
# tool's .impact/) — never agent source changes.
RUNTIME_ARTIFACTS = (".impact",)
```

Рендер-хелпер (модульный, тестируемый):
```python
_TMPL_VAR = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


def _render_tmpl(text: str, env: dict[str, str], origin: str) -> str:
    missing = sorted({m.group(1) for m in _TMPL_VAR.finditer(text)} - set(env))
    if missing:
        raise RuntimeError(f"overlay template {origin}: undefined ${{...}} vars: {', '.join(missing)}")
    return _TMPL_VAR.sub(lambda m: env[m.group(1)], text)


def _apply_overlay(workdir: Path, overlay_dir: Path, env: dict[str, str]) -> None:
    for item in sorted(Path(overlay_dir).rglob("*")):
        rel = item.relative_to(overlay_dir)
        if item.is_dir():
            (workdir / rel).mkdir(parents=True, exist_ok=True)
            continue
        dst = workdir / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        if item.name.endswith(".tmpl"):
            rendered = _render_tmpl(item.read_text(encoding="utf-8"), env, str(rel))
            dst.with_name(dst.name[: -len(".tmpl")]).write_text(rendered, encoding="utf-8")
        else:
            shutil.copy2(item, dst)
```

`create_workdir` — новая сигнатура и вызов перед `git init` (строка ~46):
```python
def create_workdir(fixture_path: Path, parent: Path | None = None,
                   overlay_dir: Path | None = None,
                   overlay_env: dict[str, str] | None = None) -> tuple[Path, str]:
    ...  # существующая копия фикстуры + срез .git
    if overlay_dir is not None:
        _apply_overlay(workdir, Path(overlay_dir), overlay_env or {})
    subprocess.run(["git", "init", "-q"], cwd=workdir, check=True)
    ...
```

`diff_workdir` — два новых pathspec-исключения после `.opencode/**`:
```python
         ":(exclude).impact",
         ":(exclude).impact/**",
```
(добавить `import re` к импортам файла).

- [ ] **Step 3.4:** Run: `.venv/bin/pytest tests/test_fixture_overlay.py tests/test_fixture.py -q` (если `tests/test_fixture.py` нет — только новый файл) — Expected: all passed.
- [ ] **Step 3.5:** Commit: `git add abench/fixture.py tests/test_fixture_overlay.py && git commit -m "feat(fixture): workdir overlay with .tmpl rendering; .impact excluded from diff"`

### Task 4: runner — threading overlay + резолв `overlay_env`

**Files:** Modify: `abench/runner.py` (строки ~145–151 и ~225)

- [ ] **Step 4.1:** В `run_experiment` до плана прогонов (один раз, fail-fast):
```python
    from .envutil import expand_env_refs
    overlay_env = {k: expand_env_refs(v) for k, v in exp.overlay_env.items()}
```
- [ ] **Step 4.2:** Вызов создания ворк-дира (строка ~225) заменить на:
```python
                workdir, sha = fx.create_workdir(
                    exp.fixture_path,
                    overlay_dir=cond.overlay,
                    overlay_env=overlay_env,
                )
```
(второй вызов `fx.create_workdir(src)` на ~491 — без изменений: дефолты None.)
- [ ] **Step 4.3:** Run: `.venv/bin/pytest tests/ -q -k "runner or fixture or config"` — Expected: passed (регрессий нет).
- [ ] **Step 4.4:** Commit: `git add abench/runner.py && git commit -m "feat(runner): thread per-condition overlay into workdir creation"`

### Task 5: grounding guard — разрешить предоставленные тулы

**Files:** Modify: `abench/prompt.py` · Modify: `tests/test_prompt.py`

- [ ] **Step 5.1: failing test** (дописать в существующий `tests/test_prompt.py`; если файла нет — создать с этим единственным тестом):
```python
def test_guard_allows_harness_provided_tools():
    from abench.prompt import GROUNDING_GUARD
    assert "provided by the harness" in GROUNDING_GUARD
```
- [ ] **Step 5.2:** Run: `.venv/bin/pytest tests/test_prompt.py -q` — Expected: FAIL.
- [ ] **Step 5.3:** В конец `GROUNDING_GUARD` (последняя строка кортежа, после "...remembered copy."):
```python
    "\n- Custom tools provided by the harness in this session (e.g. project-local "
    "tools like `impact`) ARE allowed — use them freely; they are part of the task "
    "environment, not an external source."
```
- [ ] **Step 5.4:** Run: `.venv/bin/pytest tests/test_prompt.py -q` — Expected: passed.
- [ ] **Step 5.5:** Commit: `git add abench/prompt.py tests/test_prompt.py && git commit -m "feat(prompt): grounding guard explicitly allows harness-provided tools"`

### Task 6: sandbox `cache_mounts` через `{env:}` + python3 в образе

**Files:** Modify: `abench/opencode_client.py` (цикл по `sb.cache_mounts`, ~строка 256), `docker/Dockerfile.sandbox`

- [ ] **Step 6.1:** Найти точное место: `grep -n "cache_mounts" abench/opencode_client.py`. В цикле, где каждый `mount` уходит в аргументы `-v`, обернуть значение:
```python
        from .envutil import expand_env_refs
        ...
        for mount in sb.cache_mounts:
            mount = expand_env_refs(mount)
```
(импорт — в шапку файла, не внутрь цикла).
- [ ] **Step 6.2: тест.** Если сборка docker-команды — отдельная функция (видно по grep), добавить в соответствующий тестовый файл юнит: настроить `SandboxCfg(cache_mounts=["{env:GT_HOME}:/opt/gt:ro"])`, `monkeypatch.setenv("GT_HOME", "/x")`, собрать команду, проверить `"/x:/opt/gt:ro"` в argv. Если сборка инлайнится в метод запуска — выделить чистую функцию `_resolved_mounts(sb) -> list[str]` и тестировать её.
- [ ] **Step 6.3:** В `docker/Dockerfile.sandbox` в `apt-get install` добавить `python3` (строка с `curl git unzip ca-certificates maven` → `curl git unzip ca-certificates maven python3`).
- [ ] **Step 6.4:** Run: `.venv/bin/pytest tests/ -q` — Expected: полный набор зелёный (337+ passed).
- [ ] **Step 6.5:** Commit: `git add abench/opencode_client.py docker/Dockerfile.sandbox tests/ && git commit -m "feat(sandbox): {env:NAME} in cache_mounts; python3 in sandbox image"`

---

## Ф2 — Graph-Tipper: produce_artifacts (репо `/Users/sckwoky/Projects/Graph-Tipper`)

Тесты GT гоняются так: `cd /Users/sckwoky/Projects/Graph-Tipper && PYTHONPATH=. python3 -m pytest harness/tests/impact/ -q` (stdlib-only, без venv).

### Task 7: `tools/get_joern.py`

**Files:** Create: `tools/get_joern.py`, `tools/joern.version`, `harness/tests/impact/test_get_joern.py`

- [ ] **Step 7.1: запинить версию.** На этой машине выяснить локальную: `which joern && joern --version || ls ~/joern* /opt/joern* 2>/dev/null`. Записать найденную версию (формат `vX.Y.Z`) в `tools/joern.version`; если joern локально нет — взять последний release-тег с `https://github.com/joernio/joern/releases` (одно число, без «latest»-плавания).
- [ ] **Step 7.2: failing tests**
```python
# harness/tests/impact/test_get_joern.py
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from tools.get_joern import download_url, launcher_path, is_installed

def test_download_url_pinned():
    assert download_url("v4.0.400") == (
        "https://github.com/joernio/joern/releases/download/v4.0.400/joern-cli.zip")

def test_launcher_per_platform(tmp_path):
    assert launcher_path(tmp_path, windows=False) == tmp_path / "joern-cli" / "joern"
    assert launcher_path(tmp_path, windows=True) == tmp_path / "joern-cli" / "joern.bat"

def test_is_installed_checks_launcher(tmp_path):
    assert not is_installed(tmp_path, windows=False)
    (tmp_path / "joern-cli").mkdir()
    (tmp_path / "joern-cli" / "joern").write_text("")
    assert is_installed(tmp_path, windows=False)
```
- [ ] **Step 7.3:** Run: `PYTHONPATH=. python3 -m pytest harness/tests/impact/test_get_joern.py -q` — Expected: FAIL (no module).
- [ ] **Step 7.4: имплементация**
```python
# tools/get_joern.py
"""Fetch a pinned joern-cli into <home>/joern-cli (stdlib-only, cross-platform).

Usage: python3 tools/get_joern.py [--home ~/.graph-tipper] [--version vX.Y.Z]
Prints the launcher path on success. JOERN_VERSION env overrides the pin.
"""
from __future__ import annotations

import argparse
import io
import os
import stat
import sys
import urllib.request
import zipfile
from pathlib import Path

PIN_FILE = Path(__file__).with_name("joern.version")


def pinned_version() -> str:
    return os.environ.get("JOERN_VERSION") or PIN_FILE.read_text().strip()


def download_url(version: str) -> str:
    return f"https://github.com/joernio/joern/releases/download/{version}/joern-cli.zip"


def launcher_path(home: Path, windows: bool = (os.name == "nt")) -> Path:
    return home / "joern-cli" / ("joern.bat" if windows else "joern")


def is_installed(home: Path, windows: bool = (os.name == "nt")) -> bool:
    return launcher_path(home, windows).is_file()


def install(home: Path, version: str) -> Path:
    home.mkdir(parents=True, exist_ok=True)
    url = download_url(version)
    print(f"[get_joern] downloading {url}", file=sys.stderr)
    with urllib.request.urlopen(url) as resp:
        data = resp.read()
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        zf.extractall(home)
    if os.name != "nt":  # zipfile drops the exec bit
        for p in (home / "joern-cli").rglob("*"):
            if p.is_file() and p.suffix in ("", ".sh"):
                p.chmod(p.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return launcher_path(home)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--home", type=Path, default=Path.home() / ".graph-tipper")
    ap.add_argument("--version", default=None)
    a = ap.parse_args()
    version = a.version or pinned_version()
    if not is_installed(a.home):
        install(a.home, version)
    print(launcher_path(a.home))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```
- [ ] **Step 7.5:** Run: `PYTHONPATH=. python3 -m pytest harness/tests/impact/test_get_joern.py -q` — Expected: 3 passed.
- [ ] **Step 7.6:** Commit (в GT): `git add tools/get_joern.py tools/joern.version harness/tests/impact/test_get_joern.py && git commit -m "feat(tools): cross-platform pinned joern-cli bootstrap"`

### Task 8: `produce_artifacts` — каркас стадий

**Files:** Create: `harness/impact/produce_artifacts.py`, `harness/tests/impact/test_produce_artifacts.py`

- [ ] **Step 8.1: failing tests** (каркас: стадии/`--only`/`--force`/gradlew-имя/скраб)
```python
# harness/tests/impact/test_produce_artifacts.py
import pytest
from harness.impact import produce_artifacts as pa

def test_stage_order():
    assert [s.name for s in pa.STAGES] == [
        "joern", "slice", "agent", "capture", "gen", "impact-data", "provenance"]

def test_select_only():
    assert [s.name for s in pa.select_stages("capture")] == ["capture"]
    with pytest.raises(SystemExit):
        pa.select_stages("nope")

def test_gradlew_name():
    assert pa.gradlew_cmd(windows=False) == "./gradlew"
    assert pa.gradlew_cmd(windows=True) == "gradlew.bat"

def test_scrub_absolute_paths():
    text = "x /Users/me/gt/src/Main.java:1 y C:\\Users\\me\\gt\\A.java z /home/u/p/f"
    out = pa.scrub_paths(text, roots=["/Users/me/gt/", "C:\\Users\\me\\gt\\", "/home/u/p/"])
    assert "/Users/" not in out and "C:\\" not in out and "/home/" not in out
    assert "src/Main.java:1" in out and "A.java" in out and "f" in out

def test_scrub_raises_on_leftover_abs():
    with pytest.raises(RuntimeError, match="absolute path"):
        pa.scrub_paths("see /Users/other/secret.txt", roots=["/Users/me/gt/"])
```
- [ ] **Step 8.2:** Run: `PYTHONPATH=. python3 -m pytest harness/tests/impact/test_produce_artifacts.py -q` — Expected: FAIL.
- [ ] **Step 8.3: каркас**
```python
# harness/impact/produce_artifacts.py
"""One entry to produce ALL Graph-Tipper artifacts for (project, target).

Stages: joern → slice → agent → capture → gen → impact-data → provenance.
Stdlib-only, cross-platform (gradlew/gradlew.bat, no bash). Idempotent:
a stage is skipped when its outputs exist, unless --force.

Output layout (the contract consumed by Agentic-Bench's prepare.py):
  out/slices/<method>-graph-slice.md          compact generation artifact
  out/slices/<method>-graph-slice-verbose.md  raw budget slice
  out/impact/{methods,coverage,mutation}.json impact-tool data
  out/provenance.json
"""
from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

GT_ROOT = Path(__file__).resolve().parents[2]

_ABS = re.compile(r"(?:/Users/|/home/|[A-Za-z]:\\)[^\s'\"`)\]]+")


def scrub_paths(text: str, roots: list[str]) -> str:
    for root in roots:
        text = text.replace(root, "")
    leftover = _ABS.findall(text)
    if leftover:
        raise RuntimeError(f"absolute path(s) survived scrub: {leftover[:5]}")
    return text


def gradlew_cmd(windows: bool = (os.name == "nt")) -> str:
    return "gradlew.bat" if windows else "./gradlew"


def run(cmd: list[str], cwd: Path, env: dict | None = None) -> None:
    print(f"[produce] $ {' '.join(map(str, cmd))}  (cwd={cwd})", file=sys.stderr)
    e = dict(os.environ)
    if env:
        e.update(env)
    subprocess.run([str(c) for c in cmd], cwd=str(cwd), env=e, check=True)


@dataclasses.dataclass
class Stage:
    name: str
    fn: object          # callable(Ctx) -> None
    outputs: object     # callable(Ctx) -> list[Path]; all-exist → skip


@dataclasses.dataclass
class Ctx:
    project: Path
    target_fqn: str
    slice_target: str
    tests: list[str]
    out: Path
    java_home: str | None
    with_mutation: bool
    force: bool

    @property
    def method(self) -> str:
        return self.target_fqn.rsplit(".", 1)[-1]


# --- стадии заполняются в Tasks 9–11; каркас регистрирует и гоняет их ---
STAGES: list[Stage] = []


def stage(name: str, outputs):
    def deco(fn):
        STAGES.append(Stage(name, fn, outputs))
        return fn
    return deco


def select_stages(only: str | None) -> list[Stage]:
    if only is None:
        return STAGES
    sel = [s for s in STAGES if s.name == only]
    if not sel:
        sys.exit(f"unknown stage: {only} (have: {', '.join(s.name for s in STAGES)})")
    return sel


def execute(ctx: Ctx, only: str | None = None) -> None:
    for s in select_stages(only):
        outs = s.outputs(ctx)
        if outs and all(p.exists() for p in outs) and not ctx.force:
            print(f"[produce] {s.name}: fresh, skip", file=sys.stderr)
            continue
        print(f"[produce] ── stage {s.name}", file=sys.stderr)
        s.fn(ctx)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", type=Path, required=True)
    ap.add_argument("--target-fqn", required=True)
    ap.add_argument("--slice-target", required=True)
    ap.add_argument("--tests", required=True, help="comma-separated test classes for capture")
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--with-mutation", action="store_true")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--only", default=None)
    ap.add_argument("--java-home", default=os.environ.get("JAVA_HOME"))
    a = ap.parse_args(argv)
    ctx = Ctx(a.project.resolve(), a.target_fqn, a.slice_target,
              a.tests.split(","), a.out.resolve(), a.java_home,
              a.with_mutation, a.force)
    (ctx.out / "slices").mkdir(parents=True, exist_ok=True)
    (ctx.out / "impact").mkdir(parents=True, exist_ok=True)
    execute(ctx, a.only)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```
Для прохождения `test_stage_order` УЖЕ в этом шаге зарегистрировать все 7 стадий заглушками вида `@stage("joern", outputs=lambda c: [])` с телом `raise NotImplementedError(...)` — реальные тела приходят в Tasks 9–11 (заглушки не вызываются тестами каркаса).
- [ ] **Step 8.4:** Run: тесты Task 8 — Expected: 5 passed.
- [ ] **Step 8.5:** Commit: `git add harness/impact/produce_artifacts.py harness/tests/impact/test_produce_artifacts.py && git commit -m "feat(impact): produce_artifacts stage skeleton (cross-platform)"`

### Task 9: стадии `joern` + `slice`

**Files:** Modify: `harness/impact/produce_artifacts.py` (+тесты в тот же файл тестов)

- [ ] **Step 9.1:** Выяснить, как `graph-tipper slice` находит joern: `grep -rn "joern" src/main --include="*.kt" --include="*.scala" --include="*.java" -i | grep -iv test | head`. Правило: если CLI читает env (`JOERN_HOME`/`PATH`) — стадия `joern` экспортирует его; если флаг — добавить флаг в команду стадии `slice`. Зафиксировать найденное комментарием в коде стадии.
- [ ] **Step 9.2: тела стадий** (заменить заглушки):
```python
def _joern_outputs(c: Ctx) -> list[Path]:
    home = Path.home() / ".graph-tipper"
    from tools.get_joern import launcher_path  # GT_ROOT в sys.path при -m запуске
    return [launcher_path(home)]


@stage("joern", outputs=_joern_outputs)
def s_joern(c: Ctx) -> None:
    run([sys.executable, GT_ROOT / "tools" / "get_joern.py"], cwd=GT_ROOT)


def _slice_outputs(c: Ctx) -> list[Path]:
    return [c.out / "slices" / f"{c.method}.budget.md"]


@stage("slice", outputs=_slice_outputs)
def s_slice(c: Ctx) -> None:
    bin_name = "graph-tipper.bat" if os.name == "nt" else "graph-tipper"
    cli = GT_ROOT / "build" / "install" / "graph-tipper" / "bin" / bin_name
    if not cli.exists():
        run([gradlew_cmd(), "installDist", "-q",
             *(["-Dorg.gradle.java.home=" + c.java_home] if c.java_home else [])], cwd=GT_ROOT)
    workdir = c.out / "slice-work"
    workdir.mkdir(parents=True, exist_ok=True)
    env = {"JOERN_HOME": str(Path.home() / ".graph-tipper" / "joern-cli")}  # уточнить по Step 9.1
    run([cli, "slice", "--project", c.project, "--target", c.slice_target,
         "--out", workdir], cwd=GT_ROOT, env=env)
    budgets = sorted(workdir.glob("*.budget.md"))
    assert len(budgets) == 1, f"expected exactly one budget slice, got {budgets}"
    (c.out / "slices" / f"{c.method}.budget.md").write_text(budgets[0].read_text())
```
- [ ] **Step 9.3: тест выходного контракта** (без JVM):
```python
def test_slice_outputs_named_by_method(tmp_path):
    c = pa.Ctx(tmp_path, "a.B$C.putValue", "f#t", ["T"], tmp_path, None, False, False)
    assert pa._slice_outputs(c) == [tmp_path / "slices" / "putValue.budget.md"]
```
- [ ] **Step 9.4:** Run tests — Expected: passed. Commit: `git commit -am "feat(impact): joern + slice stages"`

### Task 10: стадия `agent` (порт build_agent.sh на Python)

**Files:** Modify: `harness/impact/produce_artifacts.py` (+тесты)

- [ ] **Step 10.1: failing test** (локатор byte-buddy и манифест):
```python
def test_bytebuddy_locator_prefers_pinned(tmp_path, monkeypatch):
    cache = tmp_path / ".gradle" / "caches" / "x"
    cache.mkdir(parents=True)
    (cache / "byte-buddy-1.14.18.jar").write_bytes(b"")
    (cache / "byte-buddy-1.20.0.jar").write_bytes(b"")
    monkeypatch.setattr(pa.Path, "home", staticmethod(lambda: tmp_path))
    assert pa.find_bytebuddy().name == "byte-buddy-1.14.18.jar"

def test_agent_manifest_content():
    assert "Premain-Class: gtcov.Agent" in pa.AGENT_MANIFEST
    assert "Can-Retransform-Classes: true" in pa.AGENT_MANIFEST
```
- [ ] **Step 10.2: имплементация**
```python
BB_VERSION = "1.14.18"
BB_URL = (f"https://repo1.maven.org/maven2/net/bytebuddy/byte-buddy/"
          f"{BB_VERSION}/byte-buddy-{BB_VERSION}.jar")
AGENT_MANIFEST = ("Premain-Class: gtcov.Agent\n"
                  "Can-Retransform-Classes: true\n"
                  "Can-Redefine-Classes: true\n")
AGENT_DIR = GT_ROOT / "harness" / "impact" / "producers" / "coverage-agent"


def find_bytebuddy() -> Path | None:
    hits = sorted(Path.home().glob(f".gradle/caches/**/byte-buddy-{BB_VERSION}.jar"))
    if hits:
        return hits[0]
    hits = [p for p in Path.home().glob(".gradle/caches/**/byte-buddy-*.jar")
            if "agent" not in p.name and "dep" not in p.name]
    return sorted(hits)[0] if hits else None


def _jdk_tool(c: Ctx, name: str) -> str:
    exe = name + (".exe" if os.name == "nt" else "")
    return str(Path(c.java_home) / "bin" / exe) if c.java_home else name


def _agent_outputs(c: Ctx) -> list[Path]:
    return [AGENT_DIR / "gtcov-agent.jar", AGENT_DIR / "gtcov-boot.jar"]


@stage("agent", outputs=_agent_outputs)
def s_agent(c: Ctx) -> None:
    build = AGENT_DIR / "build"
    classes = build / "classes"
    if build.exists():
        import shutil as _sh
        _sh.rmtree(build)
    classes.mkdir(parents=True)
    bb = find_bytebuddy()
    if bb is None:
        bb = build / f"byte-buddy-{BB_VERSION}.jar"
        print(f"[produce] downloading {BB_URL}", file=sys.stderr)
        urllib.request.urlretrieve(BB_URL, bb)
    srcs = sorted((AGENT_DIR / "src" / "gtcov").glob("*.java"))
    run([_jdk_tool(c, "javac"), "--release", "11", "-cp", bb, "-d", classes, *srcs],
        cwd=AGENT_DIR)
    # boot jar: Recorder + ValueRecorder only (bootstrap loader)
    boot = build / "boot" / "gtcov"
    boot.mkdir(parents=True)
    for cls in ("Recorder.class", "ValueRecorder.class"):
        (boot / cls).write_bytes((classes / "gtcov" / cls).read_bytes())
    run([_jdk_tool(c, "jar"), "cf", AGENT_DIR / "gtcov-boot.jar",
         "-C", build / "boot", "gtcov"], cwd=AGENT_DIR)
    # agent jar: classes minus the two boot classes + exploded byte-buddy
    agent = build / "agent"
    (agent / "gtcov").mkdir(parents=True)
    for f in (classes / "gtcov").glob("*.class"):
        if f.name not in ("Recorder.class", "ValueRecorder.class"):
            (agent / "gtcov" / f.name).write_bytes(f.read_bytes())
    with zipfile.ZipFile(bb) as zf:
        for info in zf.infolist():
            if info.filename.startswith("META-INF/") or info.filename == "module-info.class":
                continue
            zf.extract(info, agent)
    (build / "MANIFEST.MF").write_text(AGENT_MANIFEST)
    run([_jdk_tool(c, "jar"), "cfm", AGENT_DIR / "gtcov-agent.jar",
         build / "MANIFEST.MF", "-C", agent, "."], cwd=AGENT_DIR)
```
- [ ] **Step 10.3:** Run tests; затем реальная сборка на этой машине: `PYTHONPATH=. python3 -m harness.impact.produce_artifacts --project ~/gt-eval/picocli --target-fqn 'picocli.CommandLine$Help$TextTable.putValue' --slice-target x --tests T --out /tmp/pa-test --only agent --force` — Expected: оба jar пересобраны.
- [ ] **Step 10.4:** Commit: `git commit -am "feat(impact): python agent-build stage (no bash)"`

### Task 11: стадии `capture` + `gen`

**Files:** Modify: `harness/impact/produce_artifacts.py` (+тесты)

- [ ] **Step 11.1:** Константа init-скрипта (контент — ровно сегодняшний рабочий):
```python
CAP_INIT = """\
def out = System.getenv('GTCAP_OUT')
def agentJar = System.getenv('GTCAP_AGENT')
def capture = System.getenv('GTCAP_CAPTURE')
gradle.allprojects { p ->
  p.tasks.withType(Test).configureEach { t ->
    t.maxParallelForks = 1
    t.forkEvery = 0
    t.jvmArgs(["-javaagent:" + agentJar + "=out=" + out + ",capture=" + capture])
  }
}
"""
```
Тест: `def test_cap_init_single_fork(): assert "maxParallelForks = 1" in pa.CAP_INIT`
- [ ] **Step 11.2: тела стадий**
```python
def _capture_outputs(c: Ctx) -> list[Path]:
    return [c.out / "capture" / "done.marker"]


@stage("capture", outputs=_capture_outputs)
def s_capture(c: Ctx) -> None:
    cap = c.out / "capture"
    cap.mkdir(parents=True, exist_ok=True)
    for old in cap.glob("values*.tsv"):
        old.unlink()
    init = Path(tempfile.gettempdir()) / "gtcap-init.gradle"
    init.write_text(CAP_INIT)
    env = {"GTCAP_OUT": str(cap),
           "GTCAP_AGENT": str(AGENT_DIR / "gtcov-agent.jar"),
           "GTCAP_CAPTURE": c.target_fqn}
    run([gradlew_cmd(), ":test",
         *[f"--tests={t}" for t in c.tests],
         "--rerun-tasks", "--init-script", init, "--console=plain",
         *(["-Dorg.gradle.java.home=" + c.java_home] if c.java_home else [])],
        cwd=c.project, env=env)
    values = sorted(cap.glob("values*.tsv"))
    assert values and any(p.stat().st_size > 0 for p in values), "capture produced no values"
    (cap / "done.marker").write_text("\n".join(p.name for p in values))


def _gen_outputs(c: Ctx) -> list[Path]:
    s = c.out / "slices"
    return [s / f"{c.method}-graph-slice.md", s / f"{c.method}-graph-slice-verbose.md"]


@stage("gen", outputs=_gen_outputs)
def s_gen(c: Ctx) -> None:
    from harness.impact.gen_artifact import build
    budget = c.out / "slices" / f"{c.method}.budget.md"
    roots = [str(c.project) + os.sep, str(c.project).replace("\\", "/") + "/"]
    compact = scrub_paths(build(budget, c.out / "capture", c.target_fqn), roots)
    verbose = scrub_paths(budget.read_text(), roots)
    (c.out / "slices" / f"{c.method}-graph-slice.md").write_text(compact)
    (c.out / "slices" / f"{c.method}-graph-slice-verbose.md").write_text(verbose)
```
- [ ] **Step 11.3:** Юнит на `_gen_outputs`-имена + Run tests — Expected: passed.
- [ ] **Step 11.4:** Commit: `git commit -am "feat(impact): capture + gen stages with built-in path scrub"`

### Task 12: стадии `impact-data` + `provenance`

**Files:** Modify: `harness/impact/produce_artifacts.py` (+тесты)

- [ ] **Step 12.1: тела**
```python
def _impact_outputs(c: Ctx) -> list[Path]:
    i = c.out / "impact"
    return [i / "methods.json", i / "coverage.json", i / "mutation.json"]


@stage("impact-data", outputs=_impact_outputs)
def s_impact_data(c: Ctx) -> None:
    from harness.impact.producers.method_index import build_method_index
    from harness.impact.producers.coverage_agent_parse import build_coverage
    from harness.impact.producers.build_all import write_artifacts
    exports = sorted((c.out / "slice-work").glob(".cache/*/export/export.json"))
    assert len(exports) == 1, f"expected one cached CPG export, got {exports}"
    methods = build_method_index(exports[0])
    cov_dir = c.out / "coverage-run"
    cov_dir.mkdir(parents=True, exist_ok=True)
    for old in cov_dir.glob("matrix*.tsv"):
        old.unlink()
    env = {"GTCAP_OUT": str(cov_dir),
           "GTCAP_AGENT": str(AGENT_DIR / "gtcov-agent.jar")}
    init = Path(tempfile.gettempdir()) / "gtcap-init.gradle"
    init.write_text(CAP_INIT)
    run([gradlew_cmd(), ":test", "--rerun-tasks", "--init-script", init,
         "--console=plain",
         *(["-Dorg.gradle.java.home=" + c.java_home] if c.java_home else [])],
        cwd=c.project, env=env)
    coverage = build_coverage(sorted(str(p) for p in cov_dir.glob("matrix*.tsv")))
    mutation: dict = {}
    if c.with_mutation:
        raise SystemExit("--with-mutation: run producers/run_mutation flow first; "
                         "wire its mutation.json here (see impact-tool-state notes)")
    write_artifacts(c.out / "impact", methods, coverage, mutation)


def _prov_outputs(c: Ctx) -> list[Path]:
    return [c.out / "provenance.json"]


def _sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _git_sha(repo: Path) -> str:
    r = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo,
                       capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else "unknown"


@stage("provenance", outputs=_prov_outputs)
def s_provenance(c: Ctx) -> None:
    files = sorted([*(c.out / "slices").glob("*-graph-slice*.md"),
                    *(c.out / "impact").glob("*.json")])
    (c.out / "provenance.json").write_text(json.dumps({
        "project_sha": _git_sha(c.project),
        "graph_tipper_sha": _git_sha(GT_ROOT),
        "target_fqn": c.target_fqn,
        "slice_target": c.slice_target,
        "tests": c.tests,
        "outputs": {str(p.relative_to(c.out)): _sha256(p) for p in files},
    }, indent=2))
```
Примечание: `--with-mutation` в v1 — явный SystemExit с инструкцией (PITest-порт — отдельная задача после Ф4, спека допускает «только за флагом»; флаг при этом честно отказывает, а не молча пишет пустышку — пустышка `{}` пишется в дефолтном пути).
- [ ] **Step 12.2:** Юнит: `_impact_outputs` имена; provenance пишет все ключи (на tmp-структуре с фейковыми файлами вызвать `s_provenance` напрямую).
- [ ] **Step 12.3:** Run GT tests (все): `PYTHONPATH=. python3 -m pytest harness/tests/impact/ -q` — Expected: 35 старых + новые passed.
- [ ] **Step 12.4:** Commit: `git commit -am "feat(impact): impact-data + provenance stages; produce_artifacts complete"`

---

## Ф3 — бенч: скрипты эксперимента (репо Agentic-Bench)

### Task 13: `strip_target.py`

**Files:** Create: `experiments/picocli-putValue/strip_target.py`, `experiments/picocli-putValue/tests/test_strip_target.py`

- [ ] **Step 13.1: failing tests**
```python
# experiments/picocli-putValue/tests/test_strip_target.py
import subprocess
import sys
from pathlib import Path
import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "strip_target.py"
SRC = """class A {
    public int keep() { return 1; }
    public Cell putValue(int row, int col, Text value) {
        if (row > 0) { throw new X(); }
        return new Cell(col, row);
    }
}
"""

def run_strip(tmp_path, sig="public Cell putValue(int row, int col, Text value)"):
    f = tmp_path / "A.java"
    f.write_text(SRC)
    return subprocess.run([sys.executable, SCRIPT, "--file", f, "--signature", sig,
                           "--stub", 'throw new UnsupportedOperationException("TODO");'],
                          capture_output=True, text=True), f

def test_strips_only_target_body(tmp_path):
    r, f = run_strip(tmp_path)
    assert r.returncode == 0, r.stderr
    out = f.read_text()
    assert 'throw new UnsupportedOperationException("TODO");' in out
    assert "return new Cell(col, row);" not in out
    assert "public int keep() { return 1; }" in out

def test_signature_not_found_fails(tmp_path):
    r, _ = run_strip(tmp_path, sig="public void nope()")
    assert r.returncode != 0 and "not found" in r.stderr
```
- [ ] **Step 13.2:** Run: `.venv/bin/pytest experiments/picocli-putValue/tests/ -q` — FAIL.
- [ ] **Step 13.3: имплементация** (порт сегодняшнего брейс-матчера):
```python
# experiments/picocli-putValue/strip_target.py
"""Replace exactly one method body with a stub (brace matching from the
signature line). Newline-preserving (keepends) so CRLF checkouts survive."""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


def strip(path: Path, signature: str, stub: str) -> tuple[int, int]:
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    hits = [i for i, l in enumerate(lines) if signature in l]
    if not hits:
        sys.exit(f"signature not found in {path}: {signature}")
    if len(hits) > 1:
        sys.exit(f"signature not unique in {path} (lines {[h+1 for h in hits]})")
    sig = hits[0]
    depth, end = 0, None
    for i in range(sig, len(lines)):
        for ch in lines[i]:
            if ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    end = i
                    break
        if end is not None:
            break
    if end is None or end <= sig:
        sys.exit(f"could not brace-match the body from line {sig + 1}")
    nl = "\r\n" if lines[sig].endswith("\r\n") else "\n"
    indent = re.match(r"\s*", lines[sig]).group(0)
    lines[sig:end + 1] = [lines[sig], f"{indent}    {stub}{nl}", f"{indent}}}{nl}"]
    path.write_text("".join(lines), encoding="utf-8")
    return sig + 1, end + 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", type=Path, required=True)
    ap.add_argument("--signature", required=True)
    ap.add_argument("--stub", required=True)
    a = ap.parse_args()
    first, last = strip(a.file, a.signature, a.stub)
    print(f"stripped lines {first}..{last} -> 3-line stub")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```
- [ ] **Step 13.4:** Run tests — passed. Commit: `git add experiments/picocli-putValue/strip_target.py experiments/picocli-putValue/tests/ && git commit -m "feat(picocli-putValue): scripted method-body strip (cross-platform)"`

### Task 14: `scripts/setup_check.py`

**Files:** Create: `scripts/setup_check.py`

- [ ] **Step 14.1: имплементация** (чистые проверки; запуск руками, юнитов нет — каждая проверка тривиальный subprocess):
```python
# scripts/setup_check.py
"""Once-per-machine readiness check for Agentic-Bench (+ optional sandbox build).

Run from an ACTIVATED venv at the repo root:
  python scripts/setup_check.py [--container] [--build-image]
"""
from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from pathlib import Path

OK, BAD = "  [ok]", "  [!!]"
fails: list[str] = []


def check(name: str, ok: bool, hint: str) -> None:
    print(f"{OK if ok else BAD} {name}")
    if not ok:
        fails.append(f"{name}: {hint}")


def out_of(cmd: list[str]) -> str:
    try:
        return subprocess.run(cmd, capture_output=True, text=True).stdout + \
               subprocess.run(cmd, capture_output=True, text=True).stderr
    except FileNotFoundError:
        return ""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--container", action="store_true")
    ap.add_argument("--build-image", action="store_true")
    a = ap.parse_args()

    check("python >= 3.10", sys.version_info >= (3, 10), "install newer python")
    try:
        import abench  # noqa: F401
        check("abench importable (venv active, pip install -e done)", True, "")
    except ImportError:
        check("abench importable", False, "python -m venv .venv; activate; pip install -e '.[dev]'")
    oc = shutil.which("opencode")
    ver = out_of(["opencode", "--version"]) if oc else ""
    check("opencode 1.15.x on PATH", bool(re.search(r"\b1\.15\.", ver)),
          "npm i -g opencode-ai")
    check("git on PATH", shutil.which("git") is not None, "install git")
    jver = out_of(["java", "-version"])
    m = re.search(r'version "(\d+)', jver)
    check("JDK 17-21 (java on PATH / JAVA_HOME)", bool(m and 17 <= int(m.group(1)) <= 21),
          "install Temurin 21 and set JAVA_HOME")
    if a.container:
        docker = shutil.which("docker") or shutil.which("podman")
        check("docker/podman", docker is not None, "install Docker Desktop (WSL2 on Windows)")
        if docker:
            have = subprocess.run([docker, "image", "inspect", "abench-sandbox:latest"],
                                  capture_output=True).returncode == 0
            if not have and a.build_image:
                subprocess.run([docker, "build", "-t", "abench-sandbox:latest",
                                "-f", "docker/Dockerfile.sandbox", "."], check=True)
                have = True
            check("abench-sandbox:latest image", have, "re-run with --build-image")
    if fails:
        print("\nFix these and re-run:\n- " + "\n- ".join(fails))
        return 1
    print("\nAll good.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```
- [ ] **Step 14.2:** Run: `.venv/bin/python scripts/setup_check.py --container` — Expected: на этой машине всё `[ok]` (образ может требовать `--build-image`).
- [ ] **Step 14.3:** Commit: `git add scripts/setup_check.py && git commit -m "feat(scripts): once-per-machine setup_check"`

### Task 15: статические файлы эксперимента

**Files:** Create: `experiments/picocli-putValue/fixture.lock`, `overlays/impact/.opencode/impact.json.tmpl`, `slices/impact-tool-briefing.md` · Modify: `.gitignore`, `experiments/picocli-putValue/experiment.yaml`

- [ ] **Step 15.1:** `fixture.lock`:
```
repo=https://github.com/remkop/picocli.git
sha=a89996315c3fe26b457e89443e3034e3e5967c49
file=src/main/java/picocli/CommandLine.java
signature=public Cell putValue(int row, int col, Text value)
stub=throw new UnsupportedOperationException("TODO: implement putValue");
```
- [ ] **Step 15.2:** `overlays/impact/.opencode/impact.json.tmpl`:
```json
{
  "harness_path": "${GRAPH_TIPPER_HOME}",
  "methods": "../.impact/methods.json",
  "coverage": "../.impact/coverage.json",
  "mutation": "../.impact/mutation.json",
  "total_tests": 2233
}
```
(`total_tests` валидируется prepare.py против coverage.json — Step 16.3.)
- [ ] **Step 15.3:** `slices/impact-tool-briefing.md`:
```markdown
# Tooling note: `impact`

This session provides a custom tool named `impact` (it is allowed — it is part
of the task environment, not an external source).

What it does: analyzes YOUR CURRENT diff (uncommitted changes) and returns,
per touched method: Tier-1 VERIFIER tests (cover AND kill mutants — run these
after every edit), Tier-2 coverers (final validation only), and mutation BLIND
SPOTS — changed lines the test suite cannot detect (a green run there proves
nothing; be extra careful and re-read the contract).

How to use it well:
1. After editing the method, call `impact` (no arguments).
2. Run the Tier-1 tests it names instead of the whole suite.
3. Treat blind-spot warnings as "the suite will not catch a mistake here".
```
- [ ] **Step 15.4:** `experiment.yaml` — целиком новое содержимое:
```yaml
name: picocli-putValue
fixture_path: ./stripped
reference_path: ./original
task_prompt: ./prompts/task.md
system_prompt: ./prompts/system.md

# Free default; OpenRouter key on this machine has no credits (checked 2026-06-10).
model: opencode/deepseek-v4-flash-free

repetitions: 3
output_dir: ./runs
timeout_s: 900

opencode:
  agent: abench
  sandbox:
    mode: container
    cache_mounts:
      - "{env:GRAPH_TIPPER_HOME}:/opt/graph-tipper:ro"
      - "{env:HOME}/.gradle:/root/.gradle:ro"

conditions:
  - {name: baseline,          augmentation: null}
  - {name: augmented,         augmentation: ./slices/putValue-graph-slice.md}
  - {name: augmented-verbose, augmentation: ./slices/putValue-graph-slice-verbose.md}
  - name: augmented-tool
    augmentation: ./slices/impact-tool-briefing.md
    overlay: ./overlays/impact

overlay_env:
  GRAPH_TIPPER_HOME: /opt/graph-tipper

target_file: src/main/java/picocli/CommandLine.java
target_methods: [putValue]

verify:
  timeout_s: 900

metrics:
  test_command_patterns:
    - "(mvn|mvnw)( |$)"
    - "(gradle|gradlew)( |$)"
    - "junit"
```
- [ ] **Step 15.5:** `.gitignore` — добавить:
```
experiments/*/overlays/impact/.impact/
experiments/*/overlays/impact/.opencode/tools/
```
- [ ] **Step 15.6:** Run: `.venv/bin/python -c "from abench.config import load_experiment; load_experiment('experiments/picocli-putValue/experiment.yaml')"` — Expected: ошибок нет (overlay-каталог существует, т.к. tmpl закоммичен). Commit: `git add -A experiments/picocli-putValue .gitignore && git commit -m "feat(picocli-putValue): 4-condition experiment, tool overlay template, briefing, fixture lock"`

### Task 16: `prepare.py`

**Files:** Create: `experiments/picocli-putValue/prepare.py`

- [ ] **Step 16.1: имплементация**
```python
# experiments/picocli-putValue/prepare.py
"""Prepare the picocli-putValue experiment end-to-end on a fresh machine.

Stages: deps -> fixtures -> artifacts -> overlay -> smoke.
  python prepare.py [--only STAGE] [--force] [--dry-run]
Needs: activated venv, GRAPH_TIPPER_HOME env, JDK 17-21, opencode 1.15.x.
"""
from __future__ import annotations

import argparse
import difflib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
LOCK = dict(line.split("=", 1) for line in
            (HERE / "fixture.lock").read_text().strip().splitlines())
GT = os.environ.get("GRAPH_TIPPER_HOME")
TARGET_FQN = "picocli.CommandLine$Help$TextTable.putValue"
SLICE_TARGET = "src/main/java/picocli/CommandLine.java#TextTable.putValue(int,int,Text)"
CAPTURE_TESTS = "picocli.HelpTest,picocli.TextTableTest"


def run(cmd, cwd=HERE, env=None):
    print(f"[prepare] $ {' '.join(map(str, cmd))}")
    e = dict(os.environ)
    if env:
        e.update(env)
    subprocess.run([str(c) for c in cmd], cwd=str(cwd), env=e, check=True)


def s_deps(force):
    sys.path.insert(0, str(HERE.parents[1] / "scripts"))
    missing = []
    if GT is None or not (Path(GT) / "harness" / "impact").is_dir():
        missing.append("GRAPH_TIPPER_HOME must point at a Graph-Tipper checkout "
                       "(git clone https://github.com/<you>/Graph-Tipper)")
    if shutil.which("opencode") is None:
        missing.append("opencode: npm i -g opencode-ai")
    if shutil.which("git") is None:
        missing.append("git")
    if missing:
        sys.exit("[prepare:deps] missing:\n- " + "\n- ".join(missing))
    print("[prepare:deps] ok (run scripts/setup_check.py for the full matrix)")


def s_fixtures(force):
    orig, stripped = HERE / "original", HERE / "stripped"
    if orig.exists() and not force:
        print("[prepare:fixtures] original/ exists, skip (use --force to redo)")
    else:
        shutil.rmtree(orig, ignore_errors=True)
        run(["git", "-c", "core.autocrlf=false", "clone", LOCK["repo"], orig])
        run(["git", "checkout", "-q", LOCK["sha"]], cwd=orig)
        shutil.rmtree(orig / ".git")
    if stripped.exists() and not force:
        print("[prepare:fixtures] stripped/ exists, skip")
        return
    shutil.rmtree(stripped, ignore_errors=True)
    shutil.copytree(orig, stripped)
    run([sys.executable, HERE / "strip_target.py",
         "--file", stripped / LOCK["file"],
         "--signature", LOCK["signature"], "--stub", LOCK["stub"]])
    gw = "gradlew.bat" if os.name == "nt" else "./gradlew"
    run([gw, "compileJava", "-q", "--console=plain"], cwd=stripped)


def s_artifacts(force):
    out = HERE / "gt-out"
    run([sys.executable, "-m", "harness.impact.produce_artifacts",
         "--project", HERE / "original", "--target-fqn", TARGET_FQN,
         "--slice-target", SLICE_TARGET, "--tests", CAPTURE_TESTS,
         "--out", out, *(["--force"] if force else [])],
        cwd=GT, env={"PYTHONPATH": GT})
    for name in ("putValue-graph-slice.md", "putValue-graph-slice-verbose.md"):
        fresh = (out / "slices" / name).read_text()
        committed = HERE / "slices" / name
        if committed.exists() and committed.read_text() != fresh:
            diff = "".join(difflib.unified_diff(
                committed.read_text().splitlines(True), fresh.splitlines(True),
                f"committed/{name}", f"fresh/{name}"))[:2000]
            print(f"[prepare:artifacts] WARNING: drift vs committed {name}:\n{diff}")
        committed.write_text(fresh)
    impact_dst = HERE / "overlays" / "impact" / ".impact"
    shutil.rmtree(impact_dst, ignore_errors=True)
    shutil.copytree(out / "impact", impact_dst)
    cov = json.loads((impact_dst / "coverage.json").read_text())
    tmpl = json.loads((HERE / "overlays" / "impact" / ".opencode" / "impact.json.tmpl")
                      .read_text().replace("${GRAPH_TIPPER_HOME}", "/x"))
    n = len(cov.get("tests", cov)) if isinstance(cov, dict) else len(cov)
    if abs(n - tmpl["total_tests"]) > tmpl["total_tests"] * 0.05:
        print(f"[prepare:artifacts] WARNING: total_tests in tmpl={tmpl['total_tests']} "
              f"vs coverage universe={n} — update the tmpl")


def s_overlay(force):
    src = Path(GT) / "integrations" / "opencode" / "tools" / "impact.ts"
    dst = HERE / "overlays" / "impact" / ".opencode" / "tools" / "impact.ts"
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    print(f"[prepare:overlay] copied {src.name} from GRAPH_TIPPER_HOME")


def s_smoke(force):
    sys.path.insert(0, str(HERE.parents[1]))
    from abench.config import load_experiment
    load_experiment(HERE / "experiment.yaml")
    print("[prepare:smoke] experiment.yaml loads & validates")
    r = subprocess.run(["opencode", "run", "-m", "opencode/deepseek-v4-flash-free",
                        "Reply with exactly: OK"], capture_output=True, text=True,
                       timeout=120)
    print("[prepare:smoke] model ping:", "ok" if "OK" in r.stdout else f"CHECK AUTH\n{r.stdout[-300:]}")


STAGES = [("deps", s_deps), ("fixtures", s_fixtures), ("artifacts", s_artifacts),
          ("overlay", s_overlay), ("smoke", s_smoke)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default=None, choices=[n for n, _ in STAGES])
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args()
    for name, fn in STAGES:
        if a.only and name != a.only:
            continue
        print(f"[prepare] ── {name}")
        fn(a.force)
    print("[prepare] done. Next: abench run experiments/picocli-putValue/experiment.yaml")


if __name__ == "__main__":
    main()
```
- [ ] **Step 16.2:** Smoke на этой машине: `cd experiments/picocli-putValue && GRAPH_TIPPER_HOME=/Users/sckwoky/Projects/Graph-Tipper ../../.venv/bin/python prepare.py --only deps` — Expected: `ok`.
- [ ] **Step 16.3:** Commit: `git add experiments/picocli-putValue/prepare.py && git commit -m "feat(picocli-putValue): prepare.py — fixtures, GT artifacts, overlay, smoke"`

### Task 17: `REPRODUCE.md`

**Files:** Create: `experiments/picocli-putValue/REPRODUCE.md` — per-OS чеклист (полный текст пишется при имплементации по этому скелету; это документ, не код):
1) клон обоих репо; 2) venv + `pip install -e ".[dev]"` (+ Windows: `.venv\Scripts\activate`); 3) `npm i -g opencode-ai`; 4) `python scripts/setup_check.py --container --build-image`; 5) `GRAPH_TIPPER_HOME=...` (`$env:` в PowerShell; плюс `set HOME=%USERPROFILE%` для `{env:HOME}`-маунта); 6) `python prepare.py`; 7) выбор `model:`; 8) `abench run ...`; 9) прислать `runs/picocli-putValue/<batch>/`. Плюс Windows-каверзы из спеки §11.5 (joern.bat/WSL-фолбэк, autocrlf, Docker Desktop, `python3`-алиас для host-режима impact.ts).
- [ ] Commit: `git add experiments/picocli-putValue/REPRODUCE.md && git commit -m "docs(picocli-putValue): per-OS reproduction checklist"`

---

## Ф4 — End-to-end на этой машине (risk-gates)

### Task 18: полный прогон пайплайна + контейнерный смоук tool-условия

- [ ] **Step 18.1:** `python scripts/setup_check.py --container --build-image` — Expected: всё ok, образ собран (теперь с python3).
- [ ] **Step 18.2:** `rm -rf experiments/picocli-putValue/{original,stripped,gt-out}` и полный `prepare.py` с `GRAPH_TIPPER_HOME=/Users/sckwoky/Projects/Graph-Tipper` — Expected: все стадии зелёные; drift-warning по срезам ПУСТОЙ (та же версия+пин) — если дрифт есть, разобраться ДО следующего шага (вероятная причина — другой joern/GT-SHA, см. provenance.json).
- [ ] **Step 18.3 (risk-gate №1):** одиночный реп tool-условия в контейнере: скопировать `experiment.yaml` → `experiment-tool-smoke.yaml`, оставить только условие `augmented-tool`, `repetitions: 1`; `abench run experiments/picocli-putValue/experiment-tool-smoke.yaml`. Проверить по trace.json: агент ВИДЕЛ тул (в системном/тул-листе) и хотя бы попытался позвать `impact` (tool_calls_by_name) и тул вернул markdown (не ошибку конфига). Если opencode в контейнере не подхватил `.opencode/tools/*.ts` — диагностика: `docker run --rm -v <workdir>:/work abench-sandbox:latest opencode run -m ... 'list your available tools'`; чинить размещение (фолбэк: `~/.config/opencode/tools/` в образе) и зафиксировать находку в спеке §11.
- [ ] **Step 18.4:** Снести smoke-yaml, прибраться, прогнать ОБА тестовых набора (bench: `.venv/bin/pytest -q`; GT: `PYTHONPATH=. python3 -m pytest harness/tests/impact/ -q`) — Expected: зелёные.
- [ ] **Step 18.5:** Финальные коммиты в обоих репо; обновить память (impact-tool-state: producer есть; bench-validity-leaks: контейнер закрывает FS-вектор).

---

## Self-review checklist (выполнен при написании)

- Спека §5↔Tasks 1–6 (overlay/конфиг/guard/mounts/python3); §6↔Tasks 7–12 (все 7 стадий); §7↔Tasks 13–17; §11↔Task 18. `--with-mutation` в v1 отказывает явно — спека говорит «за флагом», не «работает молча»; зафиксировано в Step 12.1.
- Имена сквозные: `overlay`/`overlay_env`/`expand_env_refs`/`_apply_overlay`/`RUNTIME_ARTIFACTS`; стадии `joern|slice|agent|capture|gen|impact-data|provenance`; `gtcov-agent.jar`/`gtcov-boot.jar`.
- Открытые проверки имплементации помечены конкретными командами (Step 7.1 пин joern, Step 9.1 joern-резолв CLI, Step 18.3 autodiscovery) — это исследовательские шаги с командами и правилом решения, не TBD.
