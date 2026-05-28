# Experiments

Working benchmark experiments живут здесь. Каждая подпапка — один
эксперимент, со стандартной раскладкой:

```
experiments/<name>/
  experiment.yaml         # tracked    — конфиг бенча
  prompts/
    task.md               # tracked    — что должен сделать агент
    system.md             # tracked    — фиксированный system prompt
  slices/
    <name>-slice.md       # tracked    — RAG/граф-срез(ы) для augmented-условий
  original/               # gitignored — эталонная копия целевого проекта
  stripped/               # gitignored — рабочая копия с вырезанными телами методов
  runs/                   # gitignored — артефакты `abench run`
```

Git трекает **определение** эксперимента (конфиг + промпты + срезы),
игнорит тяжёлые копии (`original/`, `stripped/`) и выходы (`runs/`).
Делиться экспериментом просто: коммитишь tracked-файлы; коллабораторы
у себя клонируют целевой проект в `original/` и `stripped/`, режут те
же методы, гоняют.

## Запуск

```bash
abench run experiments/<name>/experiment.yaml
# результаты: experiments/<name>/runs/<experiment-name>/
abench report experiments/<name>/runs/<experiment-name>   # пересобрать сводку
```

## Скаффолдинг нового эксперимента

[`picocli-putValue/`](picocli-putValue/) — готовый скелет под picocli.
Скопируй его как стартовую точку, отредактируй промпты/срез/YAML, потом
положи копии целевого проекта в `original/` и `stripped/`.

Полный пошаговый рецепт (выбор таргета, стрипинг тел, чтение метрик) —
[`../examples/real-codebase/README.md`](../examples/real-codebase/README.md).
