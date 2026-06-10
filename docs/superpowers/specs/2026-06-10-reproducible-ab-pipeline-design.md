# Воспроизводимый пайплайн A/B с per-session GT-тулом — дизайн

**Дата:** 2026-06-10
**Статус:** дизайн утверждён в диалоге, ожидает ревью спеки

## 1. Цель и контекст

Полный A/B-замер (picocli `putValue`) будет выполняться на отдельной машине. Нужен пайплайн, который позволяет: (а) собрать Agentic-Bench на чистой машине без ручной археологии, (б) подключить Graph-Tipper как **внешний** тул — и для производства артефактов-срезов, и как per-session инструмент `impact` внутри сессии агента, (в) прогнать 4 условия и отдать каталог результатов на анализ.

Сегодняшняя ручная сборка показала слабые места: граф-срез (`budget.md`) жил только в локальном `~/gt-eval`, стрип метода делался ad-hoc сниппетом, скраб абсолютных путей из срезов — руками, а per-session тула в abench нет вовсе.

## 2. Ключевые решения

1. **Условия полного A/B:** `baseline` / `augmented` (компактный GT-артефакт) / `augmented-verbose` (сырой срез) / `augmented-tool` (компактный артефакт-брифинг + per-session тул `impact`).
2. **Механизм per-session тула — workdir-overlay** с готовым opencode custom tool из GT (`integrations/opencode/tools/impact.ts`). MCP-сервер — будущая эволюция, не сейчас; overlay останется полезным и при MCP (доставка данных `.impact/`).
3. **Joern-производные артефакты регенерируются на месте** (полный from-scratch пайплайн, Joern ставится скриптом). Закоммиченные срезы остаются эталоном для сверки на дрифт, не источником.
4. **Форма — скрипты в обоих репо.** GT получает один вход «произведи все артефакты для (проект, таргет)»; бенч — `setup.sh` (раз на машину) и per-experiment `prepare.sh`. Харнесс abench не знает про GT.
5. **Прогон — в sandbox-контейнере** (`opencode.sandbox.mode=container`): закрывает вектор «агент читает эталон с хост-диска». GT монтируется в контейнер read-only; verify остаётся на хосте.
6. Граница ответственности: производство артефактов — домен GT; инжекция, изоляция и замер — домен бенча; склейка — `prepare.sh` эксперимента; единственный шов — `GRAPH_TIPPER_HOME` и фиксированная раскладка каталога-выхода GT.

## 3. Вне области

- MCP-сервер в Graph-Tipper (зафиксирован как эволюция).
- Подкоманда `abench prepare` (пайплайн живёт в скриптах).
- Правки web-UI (форма редактора возьмёт новое поле `overlay` из pydantic-схемы автоматически).
- `mutation.json` в дефолтном пути производства (PITest долгий — только за флагом `--with-mutation`).
- Кросс-эксперимент generic-универсализация скриптов: пишем для `picocli-putValue`, переносимость — через копию скелета (как принято в `experiments/`).

## 4. Архитектура: границы и поток

```
Graph-Tipper (внешний, $GRAPH_TIPPER_HOME)         Agentic-Bench
┌─────────────────────────────────────┐   ┌─────────────────────────────────────┐
│ harness/impact/produce_artifacts    │   │ setup.sh            (раз на машину) │
│   joern → CPG → slice → capture →   │ ← │ experiments/<exp>/prepare.sh        │
│   gen_artifact → impact-данные      │   │   фикстуры → GT-артефакты → overlay │
│ → out/: slices/*.md                 │ → │   → смоук                           │
│         impact/*.json               │   │ abench run          (4 усл. × N)    │
│         provenance.json             │   │   ↳ overlay в ворк-дир (до seed-    │
└─────────────────────────────────────┘   │     коммита), sandbox-контейнер     │
                                          └─────────────────────────────────────┘
```

Поток данных: `prepare.sh` клонирует фикстуры по пину → зовёт GT-producer на интактном `original/` → раскладывает срезы в `slices/` и данные тула в `overlays/impact/` → `abench run` инжектит срезы в промпт (как сейчас) и overlay в ворк-дир (новое).

## 5. abench: per-condition overlay (единственная правка харнесса)

**Конфиг.**
- `Condition.overlay: str | None = None` — путь к каталогу; в `load_experiment` резолвится относительно каталога yaml в абсолютный; валидация: указанный каталог обязан существовать.
- `Experiment.overlay_env: dict[str, str] = {}` — переменные для подстановки в файлы overlay. Значения поддерживают индирекцию `{env:NAME}` (конвенция уже есть у `ProviderCfg.api_key_env`): резолв из env процесса при старте прогона, отсутствие переменной — ошибка до первого рана.
- `SandboxCfg.cache_mounts`: host-часть записи `HOST:CONTAINER[:ro]` поддерживает ту же подстановку `{env:NAME}` (чтобы не коммитить машинно-специфичные пути).

**Раннер / fixture.**
- Overlay копируется в ворк-дир **после** копии фикстуры и **до** `git init` + seed-коммита → файлы тула попадают в HEAD, финальный дифф агента остаётся диффом только его правок.
- Подстановка при копировании — только в файлах с суффиксом **`.tmpl`**: вхождения `${NAME}` заменяются из `overlay_env`, результат пишется рядом без суффикса (`impact.json.tmpl` → `impact.json`); `${NAME}`, не объявленный в `overlay_env`, — жёсткая ошибка с именем файла и переменной. Все прочие файлы копируются байт-в-байт без анализа — у `impact.ts` собственные легитимные `${...}` (JS template literals), эвристическая подстановка по содержимому дала бы ложные ошибки.
- Исключения диффа: к существующим pathspec-исключениям (`opencode.json`, `.opencode/**`) добавляется `.impact/**` — кэш, который тул может дописывать в ворк-дире по ходу сессии, не должен попадать в `changes.patch` / `made_source_changes`.

**Grounding guard.** В `GROUNDING_GUARD` добавляется одна строка: предоставленные харнессом инструменты (project-local custom tools) разрешены и могут использоваться свободно — иначе агент может отказаться звать `impact` из-за правила «не выходи за пределы проекта».

**Контейнер.**
- `docker/Dockerfile.sandbox` += `python3` (тул `impact.ts` шеллится в `from_git.py`; impact-часть GT — stdlib-only, venv не нужен).
- GT монтируется read-only: `cache_mounts: ["{env:GRAPH_TIPPER_HOME}:/opt/graph-tipper:ro", "{env:HOME}/.gradle:/root/.gradle:ro"]`; в `overlay_env` при контейнерном режиме `GRAPH_TIPPER_HOME: /opt/graph-tipper` (константа маунта), при host-режиме — `{env:GRAPH_TIPPER_HOME}`.

**Метрики.** Вызовы тула видны бесплатно через `tool_calls_by_name["impact"]`; новых метрик не вводим.

## 6. Graph-Tipper: один вход производства артефактов

`python3 -m harness.impact.produce_artifacts` (дотягиваем существующие `producers/build_all`, `gen_artifact`, `dynamic_parse`, `render_generation` — не переписываем):

```
--project <dir>           # интактное дерево (bench original/)
--target-fqn  'picocli.CommandLine$Help$TextTable.putValue'
--slice-target 'src/main/java/picocli/CommandLine.java#TextTable.putValue(int,int,Text)'
--tests 'picocli.HelpTest,picocli.TextTableTest'   # фильтр capture-прогона
--out <dir>  [--with-mutation] [--force] [--only <stage>] [--java-home <jdk>]
```

Стадии (идемпотентные: скип при свежем выходе, `--force` пересоздаёт):
1. `joern` — проверка/бутстрап через `tools/get-joern.sh` (пин версии, override `JOERN_VERSION`);
2. `export` — CPG-экспорт проекта (кэш по content-SHA, как сейчас в `slice/.cache`);
3. `slice` — `graph-tipper slice` → `budget.md` (сборка JVM CLI `./gradlew installDist` входит в стадию);
4. `agent` — сборка gtcov (`build_agent.sh`);
5. `capture` — init-script, single-fork, `--tests` из аргумента → `values.tsv`;
6. `gen` — компактный артефакт (`gen_artifact`) + verbose (= `budget.md`); **скраб абсолютных путей встроен** и завершается assert'ом «в выходных md нет `/Users/`, `/home/`, `$HOME`-путей»;
7. `impact-data` — `methods.json` (из export) + `coverage.json` (полносьютный gtcov-прогон); `mutation.json` — только при `--with-mutation`;
8. `provenance` — `provenance.json`: SHA проекта и GT, версия Joern, аргументы, хэши всех выходов.

Раскладка `out/` (контракт для бенч-стороны): `slices/<method>-graph-slice.md`, `slices/<method>-graph-slice-verbose.md`, `impact/{methods,coverage[,mutation]}.json`, `provenance.json`.

Gradle-вызовы стадий получают `-Dorg.gradle.java.home` из `--java-home`/`JAVA_HOME` — глобальные конфиги чужой машины не трогаем.

## 7. Бенч-сторона: скрипты и файлы эксперимента

**`setup.sh`** (корень, раз на машину): venv + `pip install -e ".[dev]"`, проверки `opencode --version` (1.15.x), JDK 17–21, `docker`/`podman` при контейнерном режиме, сборка sandbox-образа.

**`experiments/picocli-putValue/prepare.sh`** — стадии (`--only <stage>`, `--force`):
1. `deps` — чек-лист зависимостей; каждая нехватка печатает «что отсутствует → какой командой получить» (в т.ч. `GRAPH_TIPPER_HOME` не задан/не собран);
2. `fixtures` — клон по `fixture.lock` → `original/`, копия → `stripped/`, стрип через `strip_target.py`, компиляционная проверка `./gradlew compileJava`;
3. `artifacts` — вызов GT-producer на `original/`; раскладка `slices/` + `overlays/impact/.impact/`; сверка свежих срезов с закоммиченными эталонами — дрифт печатается как **warning**, не ошибка (канон — регенерация);
4. `overlay` — копия `impact.ts` из `$GRAPH_TIPPER_HOME/integrations/opencode/tools/` (не вендорим в git); шаблон `impact.json.tmpl` с `${GRAPH_TIPPER_HOME}` уже лежит в git;
5. `smoke` — `load_experiment` валидация, пинг модели однострочным `opencode run`, наличие sandbox-образа;
6. `dry-run` (опционально, флаг) — 1 реп условия `augmented-tool`.

**`fixture.lock`** (коммитится):
```
repo=https://github.com/remkop/picocli.git
sha=a89996315c3fe26b457e89443e3034e3e5967c49
file=src/main/java/picocli/CommandLine.java
signature=public Cell putValue(int row, int col, Text value)
stub=throw new UnsupportedOperationException("TODO: implement putValue");
```

**`strip_target.py`** (бенч-репо, generic): `--file --signature --stub` → брейс-матчинг тела от строки сигнатуры, замена на стаб; ошибка, если сигнатура не найдена или неуникальна. Покрывается pytest.

**`slices/impact-tool-briefing.md`** (коммитится, пишется руками один раз): краткий брифинг для условия `augmented-tool` — что делает тул `impact`, что он разрешён, когда его звать (после правок, перед прогоном тестов). Это аугментация условия; сами данные тула едут overlay'ем.

**`REPRODUCE.md`** эксперимента — машинный чеклист: `setup.sh` → `export GRAPH_TIPPER_HOME=...` (+ клон/сборка GT) → `prepare.sh` → выбрать `model:` (free → `timeout_s: 900`) → `abench run` → прислать `runs/picocli-putValue/<batch>/` целиком на анализ.

**Гит-гигиена:** коммитятся скрипты, lock, briefing, шаблон `overlays/impact/.opencode/impact.json.tmpl`, эталонные срезы, REPRODUCE.md, yaml; генерируемое (`original/`, `stripped/`, `overlays/impact/.impact/`, скопированный `impact.ts`, `runs/`) — в `.gitignore`.

## 8. Итоговый experiment.yaml (эскиз)

```yaml
conditions:
  - {name: baseline,          augmentation: null}
  - {name: augmented,         augmentation: ./slices/putValue-graph-slice.md}
  - {name: augmented-verbose, augmentation: ./slices/putValue-graph-slice-verbose.md}
  - name: augmented-tool
    augmentation: ./slices/impact-tool-briefing.md
    overlay: ./overlays/impact

overlay_env:
  GRAPH_TIPPER_HOME: /opt/graph-tipper        # контейнерный путь маунта

opencode:
  sandbox:
    mode: container
    cache_mounts:
      - "{env:GRAPH_TIPPER_HOME}:/opt/graph-tipper:ro"
      - "{env:HOME}/.gradle:/root/.gradle:ro"

verify: {timeout_s: 900}
timeout_s: 900
```

## 9. Тестирование

- **abench (pytest, TDD):** overlay копируется и попадает в seed-коммит; `.tmpl` рендерится с подстановкой и теряет суффикс, не-`.tmpl` (включая файл с literal `${...}`) копируется байт-в-байт; неизвестная `${NAME}` в `.tmpl` — ошибка с именем файла; дифф/`made_source_changes` не видят `.opencode`/`.impact`; baseline-условие без overlay не затронуто; `{env:NAME}` в `cache_mounts` резолвится; валидация отсутствующего overlay-каталога падает при загрузке конфига.
- **e2e-смоук** (skip без opencode, по образцу существующих): фиктивный echo-тул в overlay → агент его видит/зовёт.
- **strip_target.py:** юниты — стрип `putValue`-подобного метода, ошибки «не найдено»/«неуникально».
- **GT-producer:** стадии — функции, покрываются GT-шным pytest (stdlib-only); интеграционно producer гоняется фазой 4.

## 10. Обработка ошибок

Скрипты: `set -euo pipefail`, каждая стадия атомарна, падение печатает имя стадии + диагностику «чего не хватает и как получить». Producer: assert на скраб путей; отсутствие Joern/JDK — понятное сообщение со ссылкой на bootstrap. abench: отсутствующий overlay-каталог и нерезолвящиеся `{env:}`/`${}` — ошибки конфигурации до первого рана, не посреди батча.

## 11. Риски и проверки фазы 4

1. **Автоподхват `<workdir>/.opencode/tools/*.ts`** опенкодом внутри контейнера — механизм валидирован в gt-eval на хосте; проверяем именно в контейнере (есть подозрение на влияние `opencode.json`, который пишет харнесс). Это главный risk-gate.
2. **JDK:** producer и verify зависят от JVM 17–21; передаём `-Dorg.gradle.java.home` явно, глобальные `~/.gradle/gradle.properties` другой машины не трогаем.
3. **Полносьютная coverage-матрица** — минуты прогона; это штатно, в `deps`-чеке предупреждаем.
4. **Модель** выбирается перед прогоном на той машине (free-tier валиден для относительных дельт; платная — сильнее сигнал); смоук-пинг ловит проблемы auth до батча.

## 12. Порядок имплементации

1. **Ф1 — abench overlay** (config + fixture/runner + guard-строка + `{env:}` в cache_mounts + Dockerfile python3), TDD, отдельный коммит.
2. **Ф2 — GT producer** (`produce_artifacts` + `get-joern.sh`), в репо Graph-Tipper.
3. **Ф3 — скрипты бенча** (`setup.sh`, `prepare.sh`, `strip_target.py`, `fixture.lock`, briefing, REPRODUCE.md, финальный yaml).
4. **Ф4 — end-to-end на этой машине** (кэши тёплые): `prepare.sh` с чистого состояния → 1-реп смоук `augmented-tool` в контейнере → фиксация результатов risk-gate №1.

## 13. Будущие расширения

MCP-сервер в GT (overlay тогда доставляет только данные `.impact/`); `abench prepare` как тонкая обёртка над скриптами; перенос overlay-механизма на другие эксперименты скелетом.
