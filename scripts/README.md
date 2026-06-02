# poke_opencode.py — дёрнуть OpenCode с ключом DeepSeek

Маленький **самодостаточный** скрипт: указываешь свой DeepSeek API-ключ, кидаешь
промпт в OpenCode и получаешь ответ модели + живой лог шагов. Не зависит от пакета
`abench` и использует **только стандартную библиотеку Python** — никакого `pip install`.

Под капотом он делает ровно то же, что и боевой адаптер харнесса
([`abench/opencode_client.py`](../abench/opencode_client.py)), только в одном файле и
без трейс-нормализации: запускает `opencode run --format json` подпроцессом и читает
JSONL-поток событий.

## Требования

- **Python 3.12+** (проверено на 3.14).
- **OpenCode CLI** в `PATH` (`opencode 1.15.x`):

  ```bash
  npm i -g opencode-ai          # или: brew install sst/tap/opencode
  opencode --version
  ```

- **DeepSeek API-ключ** (платная модель `deepseek/deepseek-chat`). Бесплатно и без
  ключа можно гонять `opencode/deepseek-v4-flash-free` — см. ниже.

## Быстрый старт

```bash
# из корня репозитория
python3 scripts/poke_opencode.py --api-key sk-ВАШ_КЛЮЧ "Сколько будет 2+2? Ответь одним числом."
```

Скрипт запишет ключ в `~/.local/share/opencode/auth.json` (тот же файл и формат, что
делает `opencode providers login`), запустит OpenCode и напечатает:

- **живой лог** шагов в **stderr** — `[tool]` вызовы, `[llm]` текст, `[step]` токены/стоимость;
- **финальный ответ модели** в **stdout** — поэтому его можно спокойно пайпить в файл.

```bash
python3 scripts/poke_opencode.py --api-key sk-... "Напиши hello world на Python" > answer.txt
```

## Как передать ключ DeepSeek

В порядке приоритета:

1. флаг `--api-key sk-...`;
2. переменная окружения `DEEPSEEK_API_KEY`;
3. интерактивный ввод (скрытый), если ничего из первого не задано;
4. `--no-write-key` — **не трогать** `auth.json` (ключ уже настроен через `opencode providers login`).

```bash
export DEEPSEEK_API_KEY=sk-...
python3 scripts/poke_opencode.py "Объясни, что делает этот код" --dir .
```

## Примеры

```bash
# промпт из stdin, плюс показать собственные INFO-логи opencode
echo "Перечисли файлы тут и кратко скажи, что за проект" \
  | python3 scripts/poke_opencode.py --no-write-key --dir . --verbose

# промпт из файла, свой таймаут
python3 scripts/poke_opencode.py --prompt-file task.md --timeout 600

# бесплатная модель — ключ не нужен вообще
python3 scripts/poke_opencode.py --no-write-key \
  --model opencode/deepseek-v4-flash-free \
  --small-model opencode/mimo-v2.5-free \
  "Привет!"
```

## Флаги

| Флаг | По умолчанию | Зачем |
|------|--------------|-------|
| `prompt` (позиционный) | — | Текст запроса. Можно вместо него `--prompt-file` или stdin. |
| `--api-key` | — | Ключ DeepSeek (иначе `$DEEPSEEK_API_KEY`, иначе спросит). |
| `--no-write-key` | off | Не писать в `auth.json` — ключ уже настроен. |
| `--model` | `deepseek/deepseek-chat` | ID модели в нотации opencode (`provider/id`). |
| `--small-model` | = `--model` | Модель для фоновых задач (заголовки, суммаризация). |
| `--dir` | временная папка | Рабочая директория, которую видит агент. |
| `--agent` | дефолтный агент opencode | Имя агента (системный промпт + права). |
| `--prompt-file` | — | Прочитать промпт из файла. |
| `--timeout` | `300` | Таймаут по «стене», секунды. |
| `--verbose` | off | Транслировать INFO-логи самого opencode в stderr. |
| `--keep-workdir` | off | Не удалять временную рабочую папку. |
| `--binary` | `opencode` | Путь к бинарю opencode. |

## Важные детали

- **`small_model` пиннится не просто так.** По умолчанию у opencode он указывает на
  *платную* модель Anthropic; на аккаунте без баланса фоновые задачи падают с `HTTP 402`
  и роняют весь прогон. Поэтому скрипт всегда прописывает `small_model` (по умолчанию —
  та же модель, что и основная, чтобы всё шло через твой ключ DeepSeek). Хочешь дешевле —
  поставь `--small-model opencode/mimo-v2.5-free`.
- **Рабочая папка.** Без `--dir` создаётся одноразовая временная папка и удаляется в конце
  (`--keep-workdir`, чтобы оставить). С `--dir` агент работает прямо в указанной директории —
  он может **создавать и менять файлы** там (запуск идёт с `--dangerously-skip-permissions`,
  т.е. без интерактивных подтверждений). Существующий `opencode.json` в этой папке
  сохраняется и восстанавливается, не затирается.
- **Коды выхода:** `0` — успех, `1` — ошибка (в т.ч. rate-limit `429`), `124` — таймаут,
  `127` — `opencode` не найден.

## Связь с харнессом

Это упрощённый «потыкать руками» вариант. Полный прогон с двумя условиями
(`baseline`/`augmented`), нормализованным трейсом, метриками и авто-верификацией тестов
делается через основной CLI `abench` — см. корневой [`README.md`](../README.md).
