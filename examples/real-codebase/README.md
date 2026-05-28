# Recipe — бенчить против полноценного проекта (на примере picocli)

Самодостаточный [`picocli-wordcount`](../picocli-wordcount/) — это
минимальный end-to-end демо, в нём всё уже лежит и запускается. Этот
документ — рецепт «принеси свой codebase»: как сделать всё то же самое
против настоящего opensource-проекта, в котором ты сам вырезал тело
одного метода.

Работаем внутри проекта, под директорией [`experiments/`](../../experiments/).
Для picocli уже есть готовый скелет в
[`experiments/picocli-putValue/`](../../experiments/picocli-putValue/) —
дальше будем считать его рабочим примером; для другого таргета просто
скопируешь скелет под новым именем.

## 0. Установка abench (раз на машину)

Если abench ещё не настроен — пройди quickstart из [корневого README](../../README.md):
клонируешь репо, создаёшь `.venv`, ставишь `pip install -e ".[dev]"`,
`npm i -g opencode-ai`. Проверь, что `abench --help` запускается из
корня репо при активной venv.

Все команды ниже — из **корня репозитория**, с активной `.venv`
(`source .venv/bin/activate`).

## 1. Выбери целевой метод

Хороший таргет:

- **self-contained** — без неожиданных кросс-модульных зависимостей;
- **нетривиальное тело** — не просто `return x;`, иначе мерить нечего;
- **документированный** — Javadoc/docstring с интенцией;
- **покрыт существующими тестами** — чтобы вручную сверять корректность;
- соседний код не содержит копипасты реализации (никаких комментариев-«утечек»).

В picocli кандидаты живут во внутренних классах `picocli.CommandLine`
(`ArgSpec`, `OptionSpec`, `Help.IOptionRenderer`, `Tracer` и т.д.).
Поиск (после шага 2):

```bash
grep -rn "\bputValue\b" experiments/picocli-putValue/stripped/src/main/java | head
```

Запиши путь к файлу и сигнатуру выбранного метода.

## 2. Заполни скелет: клонируй проект в `original/` и `stripped/`

Скелет [`experiments/picocli-putValue/`](../../experiments/picocli-putValue/)
уже содержит конфиг, промпты и плейсхолдер среза. Тебе нужно завести
**две копии** целевого проекта прямо внутри него:

```bash
cd experiments/picocli-putValue

git clone https://github.com/remkop/picocli.git original     # эталон; агент не видит
cp -R original stripped                                       # фикстур; вырежешь тело
```

Обе папки в `.gitignore` (паттерн `experiments/*/original/` и
`experiments/*/stripped/`) — git не будет тащить ~80 МБ исходников
дважды. Харнесс на каждый прогон скопирует `stripped/` ещё раз в свежую
`/tmp/abench-...`, срежет `.git` и сделает `git init` + один коммит.

## 3. Вырежи тело метода в `stripped/`

Открой целевой файл (например, `stripped/src/main/java/picocli/CommandLine.java`)
в IDE, найди выбранный метод, замени **только тело** на `throw new
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
> одинаков в обоих условиях. «Утечка» — оригинальное **тело**, которое
> теперь живёт только в `original/` вне досягаемости агента.

Если нужно вырезать несколько методов — повтори правку. Харнесс
method-агностичен.

## 4. Промпты и срез

В скелете уже лежат:

- `prompts/task.md` — общая формулировка для restore `putValue(...)` в
  `CommandLine.java`. Если ты целишься в другой файл или метод, поправь
  путь и имя.
- `prompts/system.md` — фиксированный system prompt (одинаков в обоих
  условиях).
- `slices/putValue-graph-slice.md` — **плейсхолдер**. Замени его на
  настоящий срез от твоей RAG/граф-системы (или handmade-подсказку для
  smoke-прогона; пример формата — в
  `examples/picocli-wordcount/slices/countwords-graph-slice.md`).

`experiment.yaml` уже сконфигурирован: модель
`opencode/deepseek-v4-flash-free` (бесплатно), `repetitions: 3`, два
условия `baseline` + `augmented`, регэкспы для определения
`mvn`/`gradle`/`junit`. Чтобы перевести на свою DeepSeek-подписку:

```yaml
model: deepseek/deepseek-chat          # после `opencode providers login`
# или
model: openrouter/deepseek/deepseek-chat-v3.1
```

## 5. Запуск

Из корня репозитория, при активной venv:

```bash
abench run experiments/picocli-putValue/experiment.yaml
```

picocli — ~80 МБ. На macOS APFS каждая поприёмная копия — это
copy-on-write клон (мгновенно); на других ФС — несколько секунд на
копию. На 6 прогонов (2 условия × 3 повтора) на бесплатной модели —
закладывай 15–30 мин (free-tier rate-limits + время самого исследования
агентом доминируют).

Прогресс live из соседнего шелла:
```bash
tail -f experiments/picocli-putValue/runs/picocli-putValue/baseline/rep_0/events.jsonl
```

## 6. Что смотреть в результатах

```
experiments/picocli-putValue/runs/picocli-putValue/
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
`original/src/main/java/picocli/CommandLine.java`. Простави
`success: true|false` в `metrics.json` этого прогона и пересобери сводку:

```bash
abench report experiments/picocli-putValue/runs/picocli-putValue
```

## 7. Подводные камни

- **`.git` снимается автоматически** в temp-workdir перед каждым
  прогоном → агент не может `git log`/`git show` достать оригинал.
- **`original/` и `stripped/` в `.gitignore`** — паттерн
  `experiments/*/original/` и `experiments/*/stripped/`. Делишься
  экспериментом через коммит `experiment.yaml` + `prompts/` + `slices/`;
  коллабораторы у себя клонируют целевой проект сами.
- **Maven/Gradle нет в `PATH`?** Не критично — агент попробует
  `mvn test`, команда упадёт, но `n_test_runs` всё равно зафиксирует
  попытку. Для процессных метрик рабочий build-environment не нужен.
- **Разворот `~`.** `~/...` в YAML-путях НЕ разворачивается загрузчиком;
  используй относительные (рекомендовано — пути в скелете относительны
  YAML) или абсолютные пути.
- **Повтор для другого таргета.** Скопируй скелет:
  ```
  cp -R experiments/picocli-putValue experiments/<new-name>
  ```
  Поправь `experiment.yaml` (`name`), `prompts/task.md`, перекинь
  свежие `original/`+`stripped/`, обнови slice — гоняй. В коде харнесса
  ничего менять не нужно.
- **Несколько методов сразу.** Вырежи несколько методов в одном
  фикстуре, в `task_prompt` попроси восстановить все. Метрики покажут
  суммарную работу; если нужно пер-метод — заводи отдельный эксперимент
  на каждый.
