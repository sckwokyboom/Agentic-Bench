# picocli-putValue — скелет

Эксперимент: попросить агента восстановить тело метода `putValue(...)` в
picocli. Конфиг, промпты и плейсхолдер среза трекаются git; `original/`
и `stripped/` ты заводишь у себя локально (они в `.gitignore` по
паттерну `experiments/*/original/` и `experiments/*/stripped/`).

Ниже — полный пошаговый прогон **с нуля на новой машине**. Все команды
запускаются из корня репозитория Agentic-Bench.

## 0. Установка abench (раз на машину)

```bash
git clone https://github.com/sckwokyboom/Agentic-Bench.git
cd Agentic-Bench

python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# opencode 1.15.x:
npm i -g opencode-ai
opencode --version

# (опционально) подключить DeepSeek API key:
#   opencode providers login          # выбрать DeepSeek, вставить ключ
# затем в experiment.yaml ниже:
#   model: deepseek/deepseek-chat
# По умолчанию используется бесплатная opencode/deepseek-v4-flash-free
# — никаких внешних ключей не требуется.

# Проверка:
abench --help
```

## 1. Заполни фикстуры

Клонируем picocli в `original/` и `stripped/` (обе папки в `.gitignore`):

```bash
cd experiments/picocli-putValue

git clone https://github.com/remkop/picocli.git original
cp -R original stripped
```

## 2. Вырежи тело целевого метода в `stripped/`

Открой `stripped/src/main/java/picocli/CommandLine.java` (или другой
файл с интересующим `putValue(...)`), найди метод и замени **только
его тело** на:

```java
throw new UnsupportedOperationException(
    "TODO: implement putValue (see Javadoc and call sites)");
```

Сигнатуру, Javadoc, аннотации и окружающий код **не трогай** — это
контекст, одинаковый в обоих условиях. Javadoc на методе не считается
утечкой; «утечка» — это оригинальное **тело**, которое теперь живёт
только в `original/`.

## 3. (Опционально) Положи реальный срез

`slices/putValue-graph-slice.md` — плейсхолдер. Для реального прогона
твоя RAG/граф-система пишет сюда срез под выбранный таргет; для
handmade smoke-прогона замени плейсхолдер на ручную подсказку по образцу
[`examples/picocli-wordcount/slices/countwords-graph-slice.md`](../../examples/picocli-wordcount/slices/countwords-graph-slice.md).

## 3b. Автогенерация forced-instrument аугментации (kgpool)

Раньше `slices/forced-instrument-in-test.md` собирался вручную. Теперь его
сырьё генерируется автоматически движком **kgpool** (Graph-Tipper): по одному
таргету он строит пул рантайм/статик-данных и рендерит самодостаточный
промпт-бандл `augment.prompt.md`, который прогоняешь через модель, чтобы
получить финальный `forced-instrument-in-test.md`.

**Требования (разово):** Graph-Tipper склонирован локально (движок `kgpool`);
**JDK 21**; picocli в папке `original/` из шага 1 (git-репо для неё **не
обязателен** — `make` стабит таргет с бэкапом оригинала и сам откатывает).
Укажи abench на Graph-Tipper:

```bash
abench lib add graph-tipper ~/Projects/Graph-Tipper
# либо без реестра:  export GRAPH_TIPPER_HOME=~/Projects/Graph-Tipper
```

**Собрать бандл для `putValue` и положить его в `slices/` эксперимента**
(из корня Agentic-Bench):

```bash
python scripts/augment.py \
  --project "$PWD/experiments/picocli-putValue/original" \
  --target 'picocli.CommandLine$Help$TextTable.putValue' \
  --experiment experiments/picocli-putValue
# → experiments/picocli-putValue/slices/augment.prompt.md
```

`make` сам застабит тело `putValue`, соберёт CPG-экспорт (первый прогон качает и
гоняет **joern** — нужен JDK 21) и прогонит тест-сюиту picocli под stub, затем
откатит дерево. Заложи несколько минут.

**Что в `augment.prompt.md`:** инструкция синтеза + скелет секций
`forced-instrument-in-test.md` + дайджест пула (universe covering-тестов, focus
set, рантайм-значения аргументов, контракты методов-корридора, chain-сниппеты,
failures, сводка knowledge-graph). Тело `putValue` везде показано как **stub** —
утечки реализации нет by construction (пул strict: только stubbed-прогон).

**Финальный шаг (пока вручную):** прогони `slices/augment.prompt.md` через модель
→ сохрани результат как `slices/forced-instrument-in-test.md` → в
[`experiment-forced-instrument.yaml`](experiment-forced-instrument.yaml) поле
`augmentation:` уже указывает на этот файл.

**Быстрее / движок напрямую** — переиспользовать готовый CPG-экспорт (пропустить
joern) и не гонять второй прогон под JaCoCo. Именно в такой форме генерация
прогонялась **e2e** (412 covering-тестов, все секции, leak-safe, дерево чистое):

```bash
cd ~/Projects/Graph-Tipper
PYTHONPATH=. python3 -m harness.kgpool.make \
  --project ~/gt-eval/picocli \
  --target 'picocli.CommandLine$Help$TextTable.putValue' \
  --out ~/gt-eval/kg-pool/putValue \
  --reuse-export ~/gt-eval/slice/.cache/<hash>/export/export.json \
  --skip-jacoco
# → ~/gt-eval/kg-pool/putValue/augment.prompt.md
```

Если готового экспорта нет — убери `--reuse-export`, и `make` соберёт его через
joern сам. Известное ограничение: `bytecode`-дамп для вложенных типов (`Cell`,
`Text`) не резолвит бинарные имена и мягко помечает их `// [unavailable]` — на
leak-safety и основной контент это не влияет.

## 4. Прогон

Из корня репозитория, при активной venv:

```bash
abench run experiments/picocli-putValue/experiment.yaml
```

Результаты:

```
experiments/picocli-putValue/runs/picocli-putValue/
  summary.md                              # ← начни отсюда
  summary.csv
  baseline/rep_{0,1,2}/{events.jsonl, trace.json, changes.patch, metrics.json, manifest.json}
  augmented/rep_{0,1,2}/...
```

Открой `summary.md` — таблица baseline vs augmented с дельтами по
`n_steps`, `n_reads`, `n_searches`, `n_test_runs`, `duration_s`,
`time_to_first_edit_s`. Отрицательные дельты на этих — твой эффект от RAG.

Чтобы пересобрать сводку (например, после ручной простановки `success`
в `metrics.json`):

```bash
abench report experiments/picocli-putValue/runs/picocli-putValue
```

## Примечания

- **Размер picocli ~80 МБ.** На macOS APFS каждая per-run копия — это
  copy-on-write клон (мгновенно); на других ФС — несколько секунд на
  копию. На 6 прогонов (2 × 3) на бесплатной модели — закладывай 15–30 мин.
- **`.git` срезается автоматически** в каждой per-run копии → агент не
  может `git log`/`git show` достать оригинал.
- **Maven/Gradle на PATH не обязательны.** Если их нет — агент попробует
  `mvn test`, команда упадёт, но `n_test_runs` всё равно зафиксирует
  попытку (это нужная метрика).
- **Делиться экспериментом** = коммитнуть `experiment.yaml`, `prompts/`,
  `slices/` и этот README. `original/`, `stripped/`, `runs/` уезжают в
  `.gitignore`; коллабораторы выполняют шаги 1–2 у себя.

Полный рецепт (как выбирать таргет, как точно стрипить, как читать
метрики, подводные камни) —
[`../../examples/real-codebase/README.md`](../../examples/real-codebase/README.md).
