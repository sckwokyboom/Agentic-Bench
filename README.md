# Agentic-Bench

> Python-харнесс для оценки, насколько полезны RAG-аугментации с графовыми срезами для агентной разработки.

## Зачем

Прогоняет AI-агента (OpenCode) на одной и той же задаче в выбранном проекте под двумя условиями (`baseline` и `augmented` — с дополнительным графовым контекстом от твоей RAG-системы), снимает полный агентский трейс (ReAct-цепочка: рассуждения, вызовы инструментов/команд, правки файлов) и считает метрики: сокращает ли срез цепочку, разведку кода, число запусков тестов и общее время — без потери корректности.

Корректность — пока ручная (харнесс сохраняет финальный дифф; вердикт за тобой), процессные метрики извлекаются из трейса автоматически.

## Быстрый старт — пример `picocli WordCount`

Self-contained пример лежит в [`examples/picocli-wordcount/`](examples/picocli-wordcount/) — крошечный maven + picocli + JUnit проект, в котором у метода `countWords(String text)` удалено тело; харнесс просит агента его восстановить.

```bash
git clone https://github.com/sckwokyboom/Agentic-Bench.git
cd Agentic-Bench
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# opencode 1.15.x — поставь, если ещё нет:
npm i -g opencode-ai

# (опционально) подключи DeepSeek API key:
#   opencode providers login          # выбрать DeepSeek, вставить ключ
# затем в experiment.yaml:
#   model: deepseek/deepseek-chat
# (по умолчанию пример использует opencode/deepseek-v4-flash-free — бесплатно, без ключа)

abench run examples/picocli-wordcount/experiment.yaml
# результаты: examples/picocli-wordcount/runs/picocli-countwords/summary.md
```

Полный пошаговый README с расшифровкой каждой метрики — [`examples/picocli-wordcount/README.md`](examples/picocli-wordcount/README.md).

## Архитектура

Два шва изоляции:

1. **OpenCode-адаптер** (`abench/opencode_client.py`) — единственный модуль, знающий специфику opencode. Гоняет `opencode run --format json` как subprocess, читает JSONL-поток событий live, потом `opencode export <id>` для финальной персистентной сессии, выдаёт нормализованный `Trace`.
2. **Нормализованный трейс** (`abench/trace_model.py`) — `Step` / `StepKind` / `Trace` нейтральные; `metrics.extract` / `report` работают только с ними → анализ language- и provider-агностичен.

Пайплайн одного прогона:

```
fixture (копия + git init + один коммит, .git вырезан)
  → user-промпт (task ± augmentation)
  → opencode run → JSONL events (live) + opencode export (canonical)
  → normalize() → Trace
  → metrics.extract(trace, diff) → metrics.json + changes.patch + manifest.json
```

Подробности — [`docs/superpowers/specs/2026-05-27-agentic-bench-design.md`](docs/superpowers/specs/2026-05-27-agentic-bench-design.md).

## Карта репозитория

```
abench/                            # Python-пакет
  config.py                        # YAML эксперимента → типизированные модели (pydantic)
  fixture.py                       # копия фикстура + git init + diff + cleanup
  prompt.py                        # compose(task, augmentation)
  opencode_client.py               # RealOpenCodeClient (subprocess + JSONL + export)
  trace_normalize.py               # raw events + session → нормализованный Trace
  trace_model.py                   # Step / StepKind / Trace
  diffstat.py                      # parse_diffstat(patch) → (files, +, −)
  metrics.py                       # extract(trace, patch, cfg) → metrics dict
  runner.py                        # цикл condition × repetition + артефакты
  report.py                        # pandas-агрегация → summary.csv + summary.md
  cli.py                           # abench run / abench report
tests/                             # 21 теста, включая два e2e на реальный opencode
examples/picocli-wordcount/        # готовый end-to-end пример (синтетический мини-проект)
examples/real-codebase/            # рецепт «принеси свой codebase» (на примере picocli)
experiments/                       # рабочие эксперименты (определения трекаются, тяжёлые копии — в .gitignore)
  picocli-putValue/                #   ↳ скелет под picocli/putValue — клонируешь picocli в ./original и ./stripped
docs/superpowers/
  specs/                           # дизайн-спека
  plans/                           # план реализации
  notes/opencode-api.md            # верифицированный API OpenCode (после spike Фазы 2)
```

## Метрики

`metrics.json` каждого прогона содержит:

| Ключ | Смысл |
|---|---|
| `duration_s` | wall-clock прогона |
| `n_steps` | различных модельных шагов — длина ReAct-цепочки |
| `n_tool_calls` (+ `tool_calls_by_name`) | всего tool-вызовов + разбивка по имени |
| `n_test_runs` | bash-команды, матчащие `test_command_patterns` (`pytest`/`mvn`/`gradle`/…) |
| `n_reads` / `n_searches` | read/grep/glob/list — «объём разведки кода» |
| `n_files_edited`, `diff_lines_added/removed` | из git-диффа против исходного коммита |
| `tokens_in/out`, `cost` | из персистентной сессии (агрегированно) |
| `time_to_first_edit_s` | от старта до первой правки |
| `finished` | дошёл ли агент сам до конца |
| `interrupted_reason` | `null` \| `timeout` \| `rate_limit` \| `error` |
| `success` | `null` — заполняешь вручную после сверки с `reference_path` |

`summary.md` агрегирует mean/median/std по условиям (исключая прогоны с `interrupted_reason != null`) и показывает дельту `augmented vs baseline` в процентах. Отрицательные дельты на `n_steps`, `n_reads`, `n_searches`, `n_test_runs`, `duration_s` — это и есть искомый эффект RAG.

## Тесты

```bash
.venv/bin/pytest -q              # 21 passed
```

Два интеграционных теста (`tests/test_opencode_client_integration.py`, `tests/test_run_e2e.py`) гоняют **реальный** opencode на бесплатной модели и авто-скипаются, если `opencode` нет в `PATH`.

## Документация

- Дизайн-спека: [`docs/superpowers/specs/2026-05-27-agentic-bench-design.md`](docs/superpowers/specs/2026-05-27-agentic-bench-design.md)
- План реализации: [`docs/superpowers/plans/2026-05-27-agentic-bench.md`](docs/superpowers/plans/2026-05-27-agentic-bench.md)
- Заметки по реальному API OpenCode: [`docs/superpowers/notes/opencode-api.md`](docs/superpowers/notes/opencode-api.md)
- Разбор синтетического примера и метрик: [`examples/picocli-wordcount/README.md`](examples/picocli-wordcount/README.md)
- Рецепт для полноценного проекта (`picocli` + стрипнутый `putValue`): [`examples/real-codebase/README.md`](examples/real-codebase/README.md)
- Соглашение о директории `experiments/` и скелет под picocli: [`experiments/README.md`](experiments/README.md)
