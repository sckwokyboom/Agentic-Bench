# Agentic-Bench Web UI — дизайн

**Дата:** 2026-05-29
**Статус:** дизайн утверждён по разделам, ожидает финального ревью спеки
**Базовый спек проекта:** [`2026-05-27-agentic-bench-design.md`](2026-05-27-agentic-bench-design.md)

## 1. Цель

Интерактивный Web-UI поверх существующего Python-харнесса `abench`. Позволяет:

- Редактировать эксперименты в форме (rjsf-mui по pydantic JSON Schema) с live-валидацией каждого поля; невалидный YAML физически нельзя сохранить.
- Загружать `.yaml` и парсить через тот же `load_experiment` со структурированной выдачей pydantic-ошибок.
- Запускать эксперимент с live-стримом ReAct-событий из OpenCode и видеть прогресс по condition × rep.
- Авто-валидировать корректность результата через прогон проектного test-suite (`mvn test` / `./gradlew test` / `pytest` / ...).
- Смотреть завершённый трейс как первоклассный объект анализа: turn-by-turn timeline + per-turn stats + raw events + final diff + method comparison.

Local-only, single-user: запускается командой `abench-ui` на машине исследователя, браузер ходит на `localhost`. Без auth, без деплоя, без multi-user изоляции (это не научный сервис, а инструмент исследователя).

## 2. Объём v1 vs v2 vs v3+ (зафиксировано в брейншторме)

**v1 (этот спек):**

- Backend: FastAPI app — REST + WS, model-validation, providers-credentials writer, run-orchestration.
- `abench/` extensions:
  - `VerifyCfg` в `Experiment`,
  - `Trace.turns[]`, `Trace.verify_*`, `Trace.final_diff_summary`,
  - опциональные `Experiment.target_file`, `Experiment.target_methods`,
  - новый модуль `abench/verify.py` + парсеры для Maven/Gradle/pytest/jest/cargo,
  - обновлённый `abench/trace_normalize.py` (читает `step-finish` в `TurnInfo`),
  - обновлённый `abench/runner.py` (post-rep verify в lifecycle).
- Frontend: страницы ExperimentList, ExperimentEdit (rjsf-mui), Run (live), TraceView (single trace).
- CLI: `abench-ui` console-script.

**v2 (отдельный спек/план):**

- Comparison view: side-by-side N traces, aligned step-by-step diff, кросс-condition агрегаты.
- **Heavyweight** KV-cache isolation: per-run `user` field plumbing, опциональный API-key rotation. (Lightweight: nonce-prefix + shuffle order уже в v1 — см. раздел 10.)
- Per-step timing breakdown (`llm_latency_s` per step, `tool_exec_s` per tool) + waterfall chart.
- Plots & advanced viz (matplotlib/recharts).

**v3+ (future):**

- Wizard «New experiment» с git-clone target.
- Auto-stripping (AST per language: JavaParser / tree-sitter).
- Multi-user / authenticated deployment.

## 3. Архитектура

```
┌──────────────────────────────────────────────────────────────────┐
│ Browser (localhost:8765)                                         │
│   React 18 + MUI v5 + Vite (dev) / static bundle (prod)          │
│   - editor: rjsf-mui над JSON Schema из pydantic                 │
│   - run page: live ReAct-стрим из WS                             │
│   - trace viewer: bespoke компоненты (turn timeline + stats)     │
└────────────────────────────────────────────────────────────────┘
         │ REST (CRUD experiments) + WS (live events)
┌────────▼─────────────────────────────────────────────────────────┐
│ FastAPI (single process, in-process с abench)                    │
│  /api/schema             → JSON Schema из pydantic Experiment    │
│  /api/experiments        → list / CRUD experiments/<name>/       │
│  /api/runs               → list runs, retrieve trace.json и т.д. │
│  /api/validate/model     → model availability (no chat calls)    │
│  /api/providers          → list + write credentials              │
│  /ws/sessions/{id}       → live stream при abench run            │
│                                                                  │
│  RunSession                                                      │
│    spawns thread → abench.runner.run_experiment(...)             │
│    client_factory = WSPublishingClient(RealOpenCodeClient(...))  │
│    on_event(raw) → publish на WS + delegate в abench             │
└──────────────────────────────────────────────────────────────────┘
         │ uses
┌────────▼─────────────────────────────────────────────────────────┐
│ abench/ (Python package) — расширяется                           │
│  config (+VerifyCfg, +target_file/methods)                       │
│  trace_model (+TurnInfo, +verify_*, +final_diff_summary)         │
│  trace_normalize (+читает step-finish)                           │
│  runner (+post-rep verify)                                       │
│  verify  ← новый модуль (auto-detect + parsers)                  │
└──────────────────────────────────────────────────────────────────┘
         │ writes / reads
┌────────▼─────────────────────────────────────────────────────────┐
│ experiments/<name>/{experiment.yaml, prompts/, slices/,          │
│                     original/, stripped/, runs/<...>/<arts>,     │
│                     .verify-baseline.json}                       │
└──────────────────────────────────────────────────────────────────┘
```

**Ключевые принципы:**

- **Single source of truth — pydantic.** `Experiment.model_json_schema()` отдаётся через `/api/schema`; фронт через rjsf-mui рендерит форму ровно по нему. Валидация на фронте = та же, что на бэке. Невалидный YAML физически нельзя сохранить. При загрузке `.yaml` парсим через тот же `load_experiment` — pydantic-ошибки выдаются в структурированном виде.
- **In-process runner.** UI-бэкенд не шеллит `abench run`, а вызывает `run_experiment(exp, client_factory)` напрямую. `client_factory` создаёт обёртку `WSPublishingClient(RealOpenCodeClient(...))`, чья `on_event` дублирует raw-event в WS-стрим. Никаких изменений в публичном API `abench/` не требуется — это уже была расчётная точка расширения.
- **Filesystem as primary storage.** UI читает `experiments/<name>/...` и `runs/...` напрямую. На v1 никакого SQLite-индекса; добавим в v2, если cross-run-запросы окажутся медленными.
- **Single command run.** `abench-ui` (новая console-script в `pyproject.toml`) поднимает FastAPI на `localhost:8765`, отдаёт **статический build фронта прямо из пакета**. Один процесс — один порт — без CORS-плясок.

## 4. Раскладка пакетов

```
abench_ui/                            # новый Python-пакет (в том же pyproject)
  __init__.py
  server.py                           # FastAPI app + WS routing
  schema.py                           # Experiment → JSON Schema + UI-аннотации
  experiments.py                      # /api/experiments — list / read / write
  runs.py                             # /api/runs — list / read артефактов
  validate.py                         # /api/validate/model (with TTLCache)
  providers.py                        # /api/providers/{p}/credentials → auth.json
  run_session.py                      # жизненный цикл live-прогона (thread + WS-publish)
  ws_client.py                        # WSPublishingClient (обёртка над RealOpenCodeClient)
  ws_buffer.py                        # per-session ring-buffer событий (replay при reconnect)
  cli.py                              # `abench-ui` console-script
  static/                             # build фронта; gitignored, собирается локально

web/                                  # фронт-исходники (не pip-устанавливаются)
  package.json, vite.config.ts, tsconfig.json
  src/
    main.tsx, App.tsx, api.ts
    pages/{ExperimentList, ExperimentEdit, Run, TraceView}.tsx
    components/
      EventStream.tsx                 # live WS event display
      TurnCard.tsx                    # одна turn-карточка с raw toggle + stats row
      ToolCallBlock.tsx               # одна строка tool call/result
      VerifyBlock.tsx                 # verify card (pending / passed / failed / skipped)
      FinalDiffCard.tsx               # inline-рендер changes.patch
      MethodComparisonCard.tsx        # side-by-side original vs regen
      MetricsDrawer.tsx               # боковая шторка с агрегатными метриками
      ModelValidationChip.tsx         # ✓ / ⚠ / ✗ + suggestions / Add key
      ConditionRunChip.tsx            # status pill для condition × rep в sidebar Run
```

Build фронта: `cd web && npm install && npm run build` копирует bundle в `abench_ui/static/`. CLI `abench-ui` отдаёт статику оттуда. Папка `static/` — в `.gitignore` (не коммитим сборку). Если её нет — CLI пишет «соберите фронт сначала: `cd web && npm run build`».

## 5. Data-model изменения в `abench/`

### 5.1 `abench/trace_model.py`

```python
@dataclass
class TurnInfo:
    message_id: str                    # из step-finish.messageID
    reason: str | None                 # "tool-calls" | "stop" | "length" | …
    tokens_in: int | None
    tokens_out: int | None
    tokens_reasoning: int | None
    cost: float | None
    started_at: float | None           # ts первого part этого turn'а
    ended_at: float | None             # ts step-finish

@dataclass
class FileChange:
    path: str
    added: int
    removed: int

@dataclass
class FinalDiffSummary:
    files: list[FileChange] = field(default_factory=list)
    total_added: int = 0
    total_removed: int = 0

@dataclass
class Trace:
    # — существующие поля сохраняются —

    turns: list[TurnInfo] = field(default_factory=list)

    verify_status: str | None = None             # "passed"|"failed"|"skipped"|"error"|"timeout"
    verify_command: str | None = None
    verify_duration_s: float | None = None
    verify_passed_count: int | None = None
    verify_failed_count: int | None = None
    verify_failed_names: list[str] = field(default_factory=list)  # ≤ 20

    final_diff_summary: FinalDiffSummary | None = None

    verify_baseline_unknown: bool = False     # True если baseline-тесты не зелёные;
                                              # UI пометит все verify-результаты unreliable

    isolation_nonce: str | None = None        # UUID4, вшитый в system_prompt для defeat
                                              # prefix-based KV-кэша провайдера (см. раздел 10)

    # v2 timing breakdown — placeholder поля, заполняются в Phase 2
    llm_latency_s: float | None = None
    tool_exec_s: float | None = None
```

### 5.2 `abench/trace_normalize.py`

При встрече события с `part.type == "step-finish"` — не скип, а аппенд в `trace.turns` нового `TurnInfo` (читаем `reason`, `tokens.*`, `cost`, timestamps). Существующая нормализация `Step`-ов не меняется. Если для какого-то `messageID` нет соответствующего step-finish (агент оборван) — добавляем TurnInfo с `reason=None` и таймстемпами по последним частям.

### 5.3 `abench/config.py`

```python
class VerifyCfg(BaseModel):
    command: str | None = None         # override; иначе auto-detect
    enabled: bool = True
    timeout_s: int = 300

class IsolationCfg(BaseModel):
    nonce_prefix: bool = True          # вшить UUID4-комментарий в начало system_prompt
    shuffle_order: bool = True         # рандомизировать порядок condition×rep
    # v2 heavyweight:
    user_field_template: str | None = None   # e.g. "abench-{run_uuid}"
    api_key_env_list: str | None = None      # e.g. "DEEPSEEK_API_KEY_LIST" → env с массивом

class Experiment(BaseModel):
    # — существующие поля —
    verify: VerifyCfg = Field(default_factory=VerifyCfg)
    target_file: str | None = None     # путь относительно fixture_path
    target_methods: list[str] | None = None  # имена методов/функций
    isolation: IsolationCfg = Field(default_factory=IsolationCfg)
```

`load_experiment` валидирует `target_file` (если задан) как существующий путь относительно `fixture_path`. `target_methods` валидируются грепом: каждое имя должно встречаться в `target_file` (иначе ValueError с suggestions).

### 5.4 `abench/verify.py` (новый модуль)

```python
@dataclass
class VerifyResult:
    status: Literal["passed", "failed", "skipped", "error", "timeout"]
    command: str | None
    duration_s: float | None
    passed_count: int | None
    failed_count: int | None
    failed_names: list[str]
    raw_output: str  # для записи в verify_output.log при error

def detect_command(workdir: Path) -> str | None:
    """Эвристика по файлам репо:
    - pom.xml → 'mvn test' (если ./mvnw → './mvnw test')
    - build.gradle / build.gradle.kts → './gradlew test' (если есть wrapper)
    - Cargo.toml → 'cargo test'
    - pyproject.toml + tests/ → 'pytest'
    - package.json со scripts.test → 'npm test'
    - go.mod → 'go test ./...'
    """

def run_verify(workdir: Path, command: str, timeout_s: int) -> VerifyResult:
    """Subprocess + парсинг вывода. На timeout — kill + status='timeout'.
    На non-zero exit + успешный parse → status='failed' (тесты реально упали).
    На non-zero exit + parse fail → status='error', raw_output сохраняется."""
```

Парсеры (`verify/parsers/maven.py`, `verify/parsers/gradle.py`, ...) — каждый ~20 строк regex. Например для Maven surefire: ищем `Tests run: X, Failures: Y, Errors: Z, Skipped: W` и `Failed tests: <name1>, <name2>`.

### 5.5 `abench/runner.py`

Жизненный цикл одного rep'а получает новый шаг **verify**, между записью `metrics.json` и cleanup workdir:

1. `fixture.create_workdir(...)` (как сейчас).
2. `prompt.compose(...)` (как сейчас).
3. `client.run_task(...)` (как сейчас).
4. `fixture.diff_workdir(...)` → `changes.patch`.
5. `metrics.extract(...)` → `metrics.json`.
6. **NEW:** `verify.run_verify(workdir, command, timeout_s)` если `exp.verify.enabled`. Результат пишется в `trace.verify_*` и в `metrics.json`.
7. `manifest.json`.
8. `fixture.cleanup(...)`.

Шаг 6 ВНУТРИ `try` блока вокруг workdir — чтобы `cleanup` всё равно сработал, если verify упадёт. Verify subprocess запускается с `cwd=workdir`, чтобы build-инструмент видел модифицированные файлы.

**Pre-flight baseline:** перед первым rep эксперимента однократно — `verify.run_verify` на свежей копии `reference_path`. Кешируем в `experiments/<name>/.verify-baseline.json`:

```json
{"command": "./gradlew test", "reference_sha": "8c3f...", "status": "passed", "passed_count": 142, "ts": 1780029456}
```

Инвалидируется при изменении хеша `reference_path`. Если baseline failing — все per-rep `Trace.verify_baseline_unknown = True`; UI рендерит большой жёлтый warning сверху Run/TraceView, и `success` авто-вердикт деградирует до `None` (manual override остаётся).

### 5.6 `abench/metrics.py`

Мелкие добавки:

- `n_files_edited_by_target: dict[str, int]` (счёт edit-шагов per file) — основа UI-чипа `regen #N` в TraceView.
- В возвращаемом dict копируются `verify_*` поля и `final_diff_summary` (чтобы метрики и UI имели одинаковую модель).
- Поле `success` теперь авто:
  - `True` если `verify_status == "passed"`.
  - `False` если `verify_status == "failed"`.
  - `None` если `verify_status in {"skipped", "error", "timeout"}` (ручная разметка как override).

PATCH `/api/runs/.../{condition}/{rep}` остаётся как override для случаев без авто-вердикта.

## 6. REST + WS endpoints

```
GET    /api/schema                                          → JSON Schema Experiment
GET    /api/experiments                                     → list[{name, has_fixture, has_reference, has_runs, last_run_at}]
GET    /api/experiments/{name}                              → резолвнутый Experiment (+тексты prompt/slice)
PUT    /api/experiments/{name}                              → запись experiment.yaml + prompts/* + slices/* атомарно (temp+rename)
POST   /api/experiments/upload                              → multipart parse → preview + список ошибок
DELETE /api/experiments/{name}                              → удалить дирректорию (с подтверждением)

GET    /api/runs/{experiment_name}                          → list[{condition, rep, finished, interrupted_reason, success, started_at}]
GET    /api/runs/{experiment_name}/{condition}/{rep}/trace  → trace.json
GET    /api/runs/{experiment_name}/{condition}/{rep}/events → events.jsonl (gzip)
GET    /api/runs/{experiment_name}/{condition}/{rep}/patch  → changes.patch
GET    /api/runs/{experiment_name}/{condition}/{rep}/metrics→ metrics.json
GET    /api/runs/{experiment_name}/{condition}/{rep}/method_comparison
                                                            → {method_name, original_lines, regen_lines, equivalent}
PATCH  /api/runs/{experiment_name}/{condition}/{rep}        → body: {success?: bool} — manual override

POST   /api/validate/model                                  → body: {model} → {status, suggestions?, provider}
GET    /api/providers                                       → list[{id, configured: bool}]
POST   /api/providers/{provider}/credentials                → body: {api_key} → atomic merge в auth.json

POST   /api/runs                                            → body: {experiment_name} → {session_id}
GET    /api/sessions/{session_id}                           → {state, current_condition, current_rep, total_runs, started_at}
DELETE /api/sessions/{session_id}                           → отменить

WS     /ws/sessions/{session_id}                            → live-стрим, envelope: {type, ...payload}
       типы:
         session.started   {total_runs, conditions}
         run.started       {condition, rep, run_idx, total_runs}
         raw_event         {condition, rep, event}        ← сырой OpenCode JSONL
         run.finished      {condition, rep, metrics, finished, interrupted_reason, verify}
         session.finished  {duration_s}
         session.error     {message}
```

WS reconnect: клиент шлёт `?last_event_id=...`; сервер делает replay из `ws_buffer.py` (ring-buffer ≤ 5000 событий per session); overflow → клиент re-fetches `/api/sessions/{id}`.

## 7. UI экраны

См. макеты в `.superpowers/brainstorm/.../content/` (Screen 1 v2, Screen 2 v2, Screen 3 v2, Screen 4 v3+v4).

### 7.1 ExperimentList

App Bar + узкий sidebar (Experiments / Runs history / About) + таблица: name, status (ready / no fixture / running), runs `N (M cond × K reps)`, last run, кнопки Run / Edit / Open. Сверху + New / ↑ Upload YAML. Status вычисляется при загрузке списка (stat фикстур + наличие активной сессии для этого эксперимента).

### 7.2 ExperimentEdit

rjsf-mui над JSON Schema. Sticky right panel: Validation (агрегат всех pydantic-ошибок, клик → scroll к полю), Plan (`N × M = K runs`, прикидка времени), Fixtures (✓ exists + размер / ✗ missing + ссылка на recipe), Previous runs (короткий список).

Поле **Model** — отдельный live-валидатор (debounce 350мс):
- `✓ available` (зелёный chip) — provider authenticated + id найден в каталоге.
- `⚠ not in catalog` (амбер) + suggestions через `difflib.get_close_matches`.
- `✗ no key` (красный) + кнопка `+ Add API key` → модалка.

Модалка «Add API key»: password input + объяснение что ключ пишется в `~/.local/share/opencode/auth.json` локально. POST `/api/providers/{p}/credentials`. После сохранения — повторная валидация поля.

То же — для поля **`small_model`** (без UI-кнопки add-key, поскольку малую модель почти всегда берут из того же провайдера, что main).

Поле **`target_file`** — text + ✓/✗ stat. `target_methods` — chip-list editor (Enter добавляет).

`augmentation` каждого condition — textarea inline; backend на Save синхронит с файлом `slices/<name>.md`.

### 7.3 Run

App Bar + Cancel + общий timer. Progress header: «Run 3/6 · condition: augmented · rep: 0 · turn 4», bar (зелёное done / синее running / серое pending), мини-сводка `done/running/pending` и chip-row для verify (`🧪 verify ok: 2/2`, `baseline tests ✓ pass (cached)`, current command).

Sidebar: per-rep карточки (один condition в группе). Каждая — статус, длительность, краткие стат-числа, и **verify-chip** (`🧪 142/142` / `🧪 139/142 (3 failing)` / `🧪 running…` / `🧪 skipped`). Левая полоска карточки повторяет цвет verify-чипа.

Main: live ReAct stream — терминальный look, группировка по turn с разделителем-заголовком `━━ turn N ━━━`, цветовая кодировка (think/tool ok/tool running/err/llm text), toolblock со сводкой результата. Контролы: auto-scroll, filter (all/think/tool/edit/err).

После «agent finished» в ленте появляется явный **verify-блок**: detected build-file, command, baseline-check, running… → итог.

### 7.4 TraceView

Финальный экран finished-прогона. Минимум хрома, фокус на ленте.

- **Verdict banner** (e.g. зелёный `✓ Verified — 142/142 tests passed` или красный `✗ Verify failed — 139/142`). Под ним строка: command + duration + baseline status + общий wall-clock.
- **Aggregate stats bar** (тонкая): histogram of stop reasons (chip-row `3 tool-calls · 1 stop`), cumulative tokens.
- **Single-column turn timeline:** 1 turn-карточка ≡ 1 уникальный `messageID`. Слева тонкий рейл с номером + линия-коннектор между турнами. Внутри карточки: заголовок (короткое описание из reasoning или `→ N tool calls`) + chip `→ <step-finish.reason>` + `show raw ▾` toggle. Тело: parts В ПОРЯДКЕ ЭМИССИИ (никакого перетасовывания) — reasoning (💭), tool blocks (✓/✎ name + сводка input + duration + output snippet), llm text (🗨). Низ — per-turn stats-row (tools N · reads M · greps K · edits L · tokens in/out · cost · duration).
- **«Show raw» expansion:** раскрывается фильтрованный по messageID кусок `events.jsonl` (терминальный look) — для отладки и сверки «UI правильно интерпретирует events».
- **Verify card** — отдельный node в ленте (зелёный или красный фон) после последнего turn'а: command, duration, passed/failed counts, expandable список failing tests, кнопка «show output» → stdout/stderr build-команды.
- **Final diff card** — всегда, после verify. Заголовок (N files, +X/−Y lines, download `changes.patch`) + inline-рендер unified diff с подсветкой `+`/`−`. Длинные диффы (≥5 файлов или ≥200 строк) — первые 3 файла + «show all in full-screen» → `/runs/.../diff`.
- **Method comparison card** — только если в YAML задан `target_file` (+ опц. `target_methods`). Side-by-side: Original (reference) | Agent's regeneration · regen #N. Chip сверху: `semantically equivalent ✓` (точное совпадение тел) или `divergent (N lines differ)` (амбер) с line-level diff под колонками. Backend endpoint `/method_comparison` извлекает фрагменты по AST (Java brace-balancing / Python `ast.parse`); fallback по line-range из first hunk of patch.
- **Sticky right drawer** (свёрнут по умолчанию, кнопка `↗ Metrics` в App Bar): tool breakdown, exploration (files read, greps, tests-by-agent, time-to-first-edit), changes (files edited, target regenerations, lines), verify-card-condensed, manifest (model, fixture sha, started timestamp).
- **Footer nav:** ← prev rep · `M / N runs · summary.md` · next rep →. Свопает другой rep того же эксперимента.
- **Tabs Diff / Compare vs reference** — НЕ на главном; они теперь deep-link страницы `/runs/.../diff`, `/runs/.../compare`. Кнопки на них — из соответствующих карточек.

**Контракт fidelity (UI ↔ OpenCode):**

1. 1 turn-карточка ≡ 1 уникальный `messageID`. Никаких склеек/расщеплений по эвристикам.
2. Порядок parts внутри turn'а = порядок эмиссии (сортировка по `timestamp`). Если модель чередовала reasoning ↔ tool ↔ text — увидишь именно так.
3. `step-start` / `step-finish` не рисуются как самостоятельные ряды, но используются:
   - `step-finish.reason` → chip turn'а.
   - `step-finish.tokens.{input,output,reasoning}` → токены turn'а.
   - `step-finish.cost` → стоимость turn'а.
4. `show raw` — фильтрованный по messageID кусок `events.jsonl`. UI ничего не выдумал — можно сверить.

## 8. Validation surface

| Поле | Метод |
|---|---|
| Все поля Experiment | pydantic ValidationError → 422 со структурой `[{loc, msg, type}]` |
| `fixture_path` / `reference_path` | filesystem stat при загрузке + анти-leak guard (reference вне output_dir) |
| `model`, `small_model` | live POST `/api/validate/model`: `opencode providers list` (TTL 30s) → `opencode models <provider>` (TTL 5min) → ищем id в каталоге; suggestions через `difflib.get_close_matches` |
| `target_file` | существует относительно `fixture_path` |
| `target_methods[i]` | greppable в `target_file` (regex по имени метода/функции, language-aware: Java/Python в v1) |
| `verify.command` (если задан) | smoke check: первый токен — известный build-tool (`mvn`, `gradle`, `gradlew`, `pytest`, ...) ИЛИ путь к существующему файлу |

**Никаких chat-вызовов** при валидации Model — только metadata endpoints (`models` / `providers list`).

## 9. Verify subsystem (детали)

- **Когда:** после каждого rep, между `metrics.json` и cleanup workdir.
- **Где:** в том же workdir-копировании. Build-кеши `~/.gradle/caches`, `~/.m2` шарятся между прогонами автоматически (живут в `$HOME`).
- **Какую команду:** `experiment.yaml.verify.command` если задан; иначе auto-detect.
- **Pre-flight на baseline:** один раз при первом rep эксперимента — verify на свежей копии `reference_path`. Кешируем в `.verify-baseline.json`. Инвалидируется по хешу.
- **Опт-аут:** `verify.enabled: false` ИЛИ build-файл не найден → `verify_status = "skipped"`, `success` остаётся `null` (manual). Все остальные метрики работают.
- **Failed → success=False автоматически.** Manual override доступен через PATCH.
- **Парсеры:** Maven surefire, Gradle, pytest, jest, cargo. Каждый ~20 строк regex; если парсинг падает → `verify_status = "error"`, raw output в `verify_output.log`.

## 10. Изоляция KV-кэша провайдера между прогонами

**Проблема.** DeepSeek, Anthropic и большинство современных LLM-провайдеров применяют **prefix-based context caching**: если несколько запросов начинаются с идентичной последовательности токенов, второй+ запрос платит дешевле и отвечает быстрее. В нашем эксперименте это означает: rep 0 «прогревает» кеш, rep 1+ получает unfair latency/cost преимущество. Сравнения «baseline vs augmented» по `duration_s` / `tokens` искажаются.

`opencode/deepseek-v4-flash-free` и подобные free-эндпоинты тоже подвержены — кеш живёт на стороне провайдера независимо от стороны клиента.

**v1 — два дешёвых дефолта, оба on, конфигурируемые:**

1. **Per-run nonce-prefix в system prompt.** Перед записью workdir-local `opencode.json`, `RealOpenCodeClient` префиксит `system_prompt` парой comment-line'ов:
   ```
   # abench-run: <uuid4>
   # fixture: <fixture_sha>
   <orig system_prompt>
   ```
   Это семантически нейтрально для агента (комментарии в начале — норма) но полностью инвалидирует prefix-cache на уровне провайдера: каждая сессия начинается с уникальной последовательности токенов. UUID4 сохраняется в `Trace.isolation_nonce` для воспроизводимости и пост-аналитики кэш-эффектов. Включается через `exp.isolation.nonce_prefix: bool = True` (default).

2. **Randomized run order.** Раннер по умолчанию `random.shuffle` массива `[(cond, rep), …]`. Это распределяет любой остаточный warm-cache effect случайно между условиями вместо систематического перекоса в пользу того условия, которое идёт первым. Seed детерминированный: `hash(experiment.name + datetime.date.today().isoformat())` — даёт одну и ту же перестановку при повторном прогоне в тот же день, но разную между днями (для воспроизводимости и одновременно decorrelation). Включается через `exp.isolation.shuffle_order: bool = True` (default).

**v2 — heavyweight механизмы (отдельный спек):**

3. **Per-run `user` field в API.** Многие провайдеры поддерживают `user` как сегментирующий параметр. **Внимание:** DeepSeek и Anthropic context-cache опираются на prefix tokens, а не на `user`, поэтому самостоятельно `user` КЭШ НЕ ИЗОЛИРУЕТ для них — это полезно прежде всего как abuse-tracking + для провайдеров (OpenAI, некоторые OpenRouter роуты), которые сегментируют кеш по `user`. Требует либо изменения OpenCode (форк), либо тонкого HTTP-прокси перед opencode → выбор после probe в v2 brainstorm.

4. **API-key rotation.** `OPENROUTER_API_KEY_LIST` / `DEEPSEEK_API_KEY_LIST` — массив ключей, раннер крутит per-run. Гарантирует абсолютную изоляцию (разные счета, разные context-cache neighborhoods у провайдера). Опциональный путь для critical accuracy экспериментов.

5. **Cool-down между прогонами.** Поле `min_seconds_between_runs` уже в конфиге; для DeepSeek/Anthropic дефолт станет 60 в v2 — любой ephemeral context cache в флайт-таблицах истечёт.

**Поток применения в runner (v1):**

```python
# в start_session(...)
if exp.isolation.shuffle_order:
    order = random.Random(seed).sample(plan, k=len(plan))
else:
    order = plan

# в _run_one(...), перед записью workdir-local opencode.json
nonce = uuid4().hex if exp.isolation.nonce_prefix else None
final_system_prompt = (
    f"# abench-run: {nonce}\n# fixture: {sha}\n{exp.system_prompt}"
    if nonce else exp.system_prompt
)
trace.isolation_nonce = nonce
```

**UI (в Run-странице):**

В верхней chip-row (рядом с verify-сводкой) — маленький индикатор: `🔒 isolated (nonce + shuffled)` (зелёный) или `🔓 isolation off` (жёлтый-предупреждающий, если юзер выключил оба флага в YAML). Даёт оператору уверенность, что эксперимент изолирован корректно.

**Тестирование:**

- Юнит: `isolation.apply_nonce_prefix(system_prompt, run_uuid) -> str` — проверка формата + что оригинальный prompt сохранён ниже.
- Юнит: `isolation.shuffle_plan(plan, seed) -> list` — определённость при одном seed, разность между seed'ами.
- Integration (опц., requires DeepSeek key): два rep'а с одинаковыми условиями но разными nonce'ами → ожидаем близкие `tokens_in` (нет cache hit'ов), что проверяет реальную работу defeat'а кэша. На v1 в smoke-тестах не обязательно.

## 11. Final diff + method comparison

- `Trace.final_diff_summary` заполняется в runner после `fixture.diff_workdir()`. UI не парсит patch каждый раз — берёт сводку.
- `GET /api/runs/.../method_comparison` отдаёт `{method_name, original_lines, regen_lines, equivalent}`. Сравнение `equivalent` — нормализация whitespace + точное совпадение тел; иначе `divergent`.
- Java: AST через простой brace-balancing на сигнатуре метода (без полноценного парсера). Python: `ast.parse(file).body` + поиск `FunctionDef` по имени.
- Если `target_file` задан, а `target_methods` пуст — комparison делается над всем файлом (просто side-by-side всего файла). Это полезно для compact-фикстур типа `WordCount.java`.

## 12. Error handling — по слоям

| Слой | Сбой | Поведение |
|---|---|---|
| Form / YAML upload | pydantic ValidationError | 422 со структурой; UI рендерит inline под полем |
| Fixture/reference missing | `_validate` ValueError | Run-кнопка disabled; путь подсвечен красным |
| Provider not configured | `opencode providers list` пуст для p | поле Model `✗ no key` + кнопка `+ Add API key` |
| Model id not in catalog | `opencode models <p>` не содержит | поле Model `⚠ not in catalog` + suggestions |
| Verify-baseline failing | первый prev-run эксперимента | большой жёлтый warning в Run; per-rep verify помечен `verify_baseline_unknown` |
| Verify timeout | subprocess не уложился | `verify_status = "timeout"`; `success=None` |
| Verify parser fail | вывод не распарсился | `verify_status = "error"`; raw stdout/stderr в `verify_output.log` |
| Opencode subprocess err | уже в `RealOpenCodeClient` | `interrupted_reason ∈ {timeout, rate_limit, error}`; WS `run.finished` с reason |
| WS disconnect | браузер закрыл сокет | сервер держит ring-buffer (≤5000) per session; reconnect → replay |
| Server restart с in-flight run | потеряли in-memory RunSession | startup: чистка `.in-progress` маркеров в `runs/`; v1 документирует «не перезапускай abench-ui во время прогона» |
| Disk full / permission на fixture-copy | exception в `fixture.create_workdir` | `session.error` event; experiment aborts; UI красный banner |

## 13. Поток одного UI-инициированного прогона

1. Юзер открывает `ExperimentEdit` для `<name>`. Фронт делает `GET /api/schema` (один раз на загрузку приложения) и `GET /api/experiments/{name}` → rjsf форма с предзаполненными значениями + текстами prompts/slices.
2. Юзер правит поля. rjsf валидирует каждое поле по JSON Schema online; «Save» блокируется, пока есть ошибки. По «Save» → `PUT /api/experiments/{name}` записывает атомарно через temp+rename.
3. Юзер жмёт «▶ Run». UI: `POST /api/runs {experiment_name}` → backend создаёт `RunSession` (uuid id, thread spawn), возвращает `{session_id}`.
4. UI открывает `WS /ws/sessions/{session_id}`. Бэкенд зовёт `session.start()` (запускает thread).
5. Поток валидирует пути → если ошибка, шлёт `session.error` и WS закрывается. Иначе шлёт `session.started`.
6. Перед первым rep'ом (если кеш `.verify-baseline.json` отсутствует или хеш реф'а изменился) — verify на baseline; результат пишется и шлётся как `session.verify_baseline {status, …}`.
7. На каждый condition × rep:
   - `run.started`,
   - `abench.runner._run_one` через `WSPublishingClient(RealOpenCodeClient(...))`,
   - параллельно WS получает `raw_event` для каждого events-line,
   - после agent finished — verify, шлётся `verify.started` → `verify.finished {status, passed, failed, names[]}`,
   - `run.finished` с метриками + `verify_*`.
8. После всех runs — `session.finished {duration_s}`. UI закрывает WS, навигейтит на TraceView первого прогона (по умолчанию `augmented / rep_0`).

## 14. Тестовая стратегия

**Backend (Python, расширяет существующий 21-test suite):**

- **Юнит** (без opencode, без сети):
  - `schema.export()` — проверка ключевых полей JSON Schema.
  - `verify.detect_command()` — таблица фикстур (pom, gradle, pyproject, package.json, Cargo.toml).
  - Verify parsers — table-driven «образец вывода → (passed, failed, names)».
  - `validate.model()` с patch'енным opencode subprocess (mock возвращает заранее заданный вывод).
  - `providers.write_credentials()` — temp HOME, проверка атомарности и формата auth.json.
  - Trace normalize: новый тест на `TurnInfo` из step-finish (golden против committed fixture).
- **API tests** через `httpx.AsyncClient` + lifespan:
  - GET/PUT experiments — round-trip через временный `experiments/` dir.
  - schema, validate/model, providers — happy + edge cases.
- **WS test:** `TestClient.websocket_connect` + FakeOpenCodeClient (уже существует) — гоняем синтетический run, проверяем последовательность WS-сообщений + replay при ремите.
- **Verify integration:** tiny maven-фикстур (под `tests/fixtures/verify-maven/`) + реальный `mvn test` — skip если mvn нет в PATH. Один тест на pass, один на fail (модифицируем source файл), один на timeout.

**Frontend (TypeScript):**

- **Vitest** (pure utilities):
  - event-group-by-messageID, stop-reason histogram, regen-counter.
  - schema → form-defaults генератор.
- **React Testing Library** (компоненты):
  - TurnCard рендерит, разворачивает raw events.
  - ModelValidationChip — все 3 состояния.
  - VerifyBlock — все статусы.
  - FinalDiffCard — рендер + collapse.
- **E2E через Playwright** (один happy-path test, опц. в v1):
  - открыть список → редактировать → save → run с mocked WS → trace view.

**Контракты:**

- JSON Schema — единственный источник правды.
- TypeScript-типы — генерация через `openapi-typescript` из автогенерированной FastAPI `openapi.json`. Build-step в `web/package.json`.

## 15. Открытые вопросы (под решение при импл)

- **Built-frontend в Python-пакете?** Для local-only можно не коммитить `static/`, требовать `npm run build` локально. Помечено в спеке; финальное решение при импл.
- **`model` autocomplete:** datalist с каталогом из всех настроенных провайдеров. Может быть 200+ опций; нужен фильтр / `MUI Autocomplete` с virtualized list.
- **WS-buffer 5000 событий** — на 6 прогонов × ~50 событий каждый = 300; запас x16. Если окажется мало для длинных experiments — увеличим.
- **Method comparison fallback** при отсутствии AST-поддержки языка — на v1 берём line-range из first hunk of patch + N контекстных строк. Доводим в v2 через tree-sitter.
- **Поведение при изменении `experiment.yaml` во время running session** — на v1 блокируем PUT, отвечаем 409 с подсказкой «cancel session first or wait».

## 16. Phase-2 заложенные точки расширения

- `Trace.llm_latency_s`, `Trace.tool_exec_s` — поля уже есть, заполняются нормализатором в v2 (timing breakdown).
- DeepSeek isolation (heavyweight): v1 уже несёт nonce-prefix + shuffle (раздел 10). В v2 добавится `user` field плумбинг (если provider честно сегментирует кеш по `user`) или тонкая HTTP-прокси-обёртка перед OpenCode'ом + API-key rotation — конкретный механизм фиксируется в v2-спеке после probe.
- Comparison view: отдельная страница `/compare?runs=...`; pandas на бэке агрегирует и отдаёт результат — никаких изменений в существующих модулях.
