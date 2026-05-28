# Recipe — бенчить против полноценного проекта (на примере picocli)

Самодостаточный пример [`picocli-wordcount`](../picocli-wordcount/) — это
минимальный демо-end-to-end, в нём всё уже лежит и запускается. Этот же
документ — рецепт «принеси свой codebase»: как сделать всё то же самое
против настоящего opensource-проекта, в котором ты сам вырезал тело
одного метода. В качестве рабочего примера — `remkop/picocli` и
гипотетический `putValue(...)`, но шаги работают для любого Maven /
Gradle / Cargo / pip проекта.

## 1. Выбери целевой метод

Хороший таргет:

- **self-contained** — без неожиданных кросс-модульных зависимостей;
- **нетривиальное тело** — не просто `return x;`, иначе мерить нечего;
- **документированный** — Javadoc/docstring с интенцией;
- **покрыт существующими тестами** — чтобы вручную сверять корректность;
- соседний код не содержит копипасты реализации (никаких комментариев-«утечек»).

В picocli кандидаты живут во внутренних классах `picocli.CommandLine`
(`ArgSpec`, `OptionSpec`, `Help.IOptionRenderer`, `Tracer` и т.д.).
Поиск:

```bash
git clone https://github.com/remkop/picocli.git ~/abench-targets/picocli-source
cd ~/abench-targets/picocli-source
grep -rn "\\bputValue\\b" src/main/java | head
# подойдёт любой метод; запиши путь к файлу и сигнатуру
```

## 2. Сделай две копии

Всё хозяйство одного эксперимента — в отдельной директории под `~/abench-experiments/`:

```bash
mkdir -p ~/abench-experiments/picocli-putValue
cd ~/abench-experiments/picocli-putValue

cp -R ~/abench-targets/picocli-source picocli-original     # эталон; агент его не видит
cp -R ~/abench-targets/picocli-source picocli-stripped     # фикстур; в нём вырежем тело
```

Харнесс на каждый прогон скопирует `picocli-stripped/` ещё раз в свежую
`/tmp/abench-...`, срежет `.git` и сделает `git init` + один коммит —
эти две папки остаются нетронутыми «ингредиентами».

## 3. Вырежи тело метода в `picocli-stripped/`

Открой файл (напр. `src/main/java/picocli/CommandLine.java`) в IDE,
найди целевой метод, замени **только тело** на `throw new
UnsupportedOperationException(...)`. Сигнатуру, Javadoc, аннотации и
окружающий код оставь как есть.

Было:
```java
void putValue(String name, Object value) {
    Assert.notNull(name, "name");
    map.put(name, value);
    fireValueChanged(name, value);
}
```

Стало:
```java
void putValue(String name, Object value) {
    throw new UnsupportedOperationException(
        "TODO: implement putValue (see Javadoc and call sites)");
}
```

> Javadoc на методе `putValue` — это **не утечка**: это контекст, и он
> одинаков в обоих условиях. «Утечка» — это оригинальное **тело**,
> которое теперь живёт только в `picocli-original/` вне досягаемости агента.

Если хочешь вырезать несколько методов — повтори правку. Харнесс
method-агностичен.

## 4. Собери эксперимент

В той же `~/abench-experiments/picocli-putValue/` создай:

`prompts/task.md`:
```
The body of method `putValue(String name, Object value)` in
`src/main/java/picocli/CommandLine.java` has been replaced with
`throw new UnsupportedOperationException(...)`. Restore the body.

Constraints:
- Do NOT modify any file other than `CommandLine.java`.
- Keep the method signature exactly as it is.
- Do not edit tests; they describe the contract.
- When done, briefly summarise what you implemented.
```

`prompts/system.md`:
```
You are a careful Java engineer. Make minimal, precise edits.
Read surrounding code and Javadoc before changing anything.
If you run a build or tests, do so at most once to verify the final
change — do not loop on the test runner.
Stay focused on the requested method only.
End with a one-paragraph summary.
```

`slices/putValue-graph-slice.md` — срез, который твоя RAG/граф-система
выдаёт под этот таргет (контракт, граф вызовов, ожидания тестов и т.д.).
Для пробного прогона можешь сначала положить «handmade» подсказку.

`experiment.yaml`:
```yaml
name: picocli-putValue
fixture_path: ./picocli-stripped
reference_path: ./picocli-original
task_prompt: ./prompts/task.md
system_prompt: ./prompts/system.md

# По умолчанию — бесплатно, без ключа.
# После `opencode providers login`:        model: deepseek/deepseek-chat
# Или через уже подключённый OpenRouter:    model: openrouter/deepseek/deepseek-chat-v3.1
model: opencode/deepseek-v4-flash-free

repetitions: 3                 # 2 условия × 3 повтора = 6 прогонов
output_dir: ./runs
timeout_s: 600

opencode:
  agent: abench

conditions:
  - {name: baseline,  augmentation: null}
  - {name: augmented, augmentation: ./slices/putValue-graph-slice.md}

metrics:
  test_command_patterns:
    - "(mvn|mvnw)( |$)"
    - "(gradle|gradlew)( |$)"
    - "junit"
```

> Пути в YAML резолвятся **относительно директории самого YAML**, так
> что вся раскладка ниже работает без правок. Не используй `~/...` —
> загрузчик `~` не разворачивает; пиши относительные или абсолютные пути.

Финальная раскладка:
```
~/abench-experiments/picocli-putValue/
  experiment.yaml
  prompts/{task.md, system.md}
  slices/putValue-graph-slice.md
  picocli-original/            # эталон; агент не видит
  picocli-stripped/            # фикстур
  runs/                        # создаст abench
```

## 5. Запуск

```bash
cd /Users/sckwoky/Projects/Agentic-Bench
source .venv/bin/activate
abench run ~/abench-experiments/picocli-putValue/experiment.yaml
```

picocli — ~80 МБ. На macOS APFS каждая поприёмная копия — это
copy-on-write клон (мгновенно); на других ФС — несколько секунд на
копию. На 6 прогонов на бесплатной модели — закладывай 15–30 мин (free-
tier rate-limits + время самого исследования агентом доминируют).

Хочешь смотреть прогресс вживую из соседнего шелла:
```bash
tail -f ~/abench-experiments/picocli-putValue/runs/picocli-putValue/baseline/rep_0/events.jsonl
```

## 6. Что смотреть в результатах

```
~/abench-experiments/picocli-putValue/runs/picocli-putValue/
  experiment.resolved.yaml
  summary.csv
  summary.md                 # ← начни отсюда
  baseline/rep_{0,1,2}/{events.jsonl, trace.json, changes.patch, metrics.json, manifest.json}
  augmented/rep_{0,1,2}/...
```

В `summary.md` — mean каждой метрики по условиям + дельта `augmented vs
baseline` в процентах. Под гипотезу «граф-RAG сокращает ReAct-цепочку и
разведку кода» главные числа:

- `n_steps` — длина цепочки;
- `n_reads` + `n_searches` — объём разведки;
- `n_test_runs` — попытки `mvn`/`gradle`/`junit`;
- `time_to_first_edit_s` — как быстро агент перешёл к правкам;
- `duration_s` — общий wall-clock.

Отрицательные дельты на этих — твой эффект.

По каждому повтору открой `changes.patch` и сверь с оригиналом в
`picocli-original/src/main/java/picocli/CommandLine.java`. Простави
`success: true|false` в `metrics.json` этого прогона и пересобери сводку:

```bash
abench report ~/abench-experiments/picocli-putValue/runs/picocli-putValue
```

## 7. Подводные камни

- **`.git` снимается автоматически** в temp-workdir перед каждым прогоном
  → агент не может `git log`/`git show` достать оригинал.
- **Maven/Gradle нет в `PATH`?** Не критично — агент попробует
  `mvn test`, команда упадёт, но `n_test_runs` всё равно зафиксирует
  попытку. Для процессных метрик рабочий build-environment не нужен.
- **Разворот `~`.** `~/...` в YAML-путях НЕ разворачивается загрузчиком;
  используй относительные или абсолютные пути.
- **Повтор для другого метода.** Заводишь новую папку
  `~/abench-experiments/<другой>/`, копируешь `picocli-source` ещё раз
  (или клонишь `picocli-stripped` до правки), редактируешь другой файл,
  правишь `task_prompt`, гоняешь. В коде харнесса ничего менять не надо.
- **Несколько методов сразу.** Вырежи несколько методов в одном
  фикстуре, в `task_prompt` попроси восстановить все. Метрики покажут
  суммарную работу; если нужно пер-метод — заводи отдельный эксперимент
  на каждый.
