# picocli-putValue — скелет

Эксперимент: попросить агента восстановить тело метода `putValue(...)` в
picocli. Конфиг, промпты и плейсхолдер среза трекаются git; `original/`
и `stripped/` ты заводишь у себя локально (они в `.gitignore`).

## Заполни фикстуры

```bash
cd experiments/picocli-putValue

git clone https://github.com/remkop/picocli.git original
cp -R original stripped
```

В `stripped/` открой целевой файл (напр.
`src/main/java/picocli/CommandLine.java`), найди нужный `putValue(...)`
и замени **только тело** на:

```java
throw new UnsupportedOperationException(
    "TODO: implement putValue (see Javadoc and call sites)");
```

Javadoc, сигнатуру, аннотации и окружающий код **не трогай** — это
контекст, и он одинаков в обоих условиях.

RAG/граф-срез под этот таргет положи в
`slices/putValue-graph-slice.md` (там сейчас плейсхолдер с
форматтинг-подсказками).

## Запуск

```bash
cd /Users/sckwoky/Projects/Agentic-Bench
source .venv/bin/activate
abench run experiments/picocli-putValue/experiment.yaml
# результаты: experiments/picocli-putValue/runs/picocli-putValue/summary.md
```

Полный рецепт (как выбирать таргет, как точно стрипить, как читать
метрики, подводные камни) —
[`../../examples/real-codebase/README.md`](../../examples/real-codebase/README.md).
