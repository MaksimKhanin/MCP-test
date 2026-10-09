# MCP над Postgres: простой пример

В Postgres лежат метаданные датасетов: владелец, SLA свежести, время последней загрузки.
Агент через MCP читает их, решает, что делать с просроченными датасетами,
и записывает задачи в очередь `agent_tasks`.

```
agent.py (MCP-клиент + StubLLM)  --stdio-->  server.py (MCP-сервер)  --SQL-->  Postgres
```

## Файлы

| Файл | Что внутри |
|---|---|
| `db/init.sql` | Таблицы `datasets` (метаданные) и `agent_tasks` (решения агента) плюс тестовые данные |
| `server.py` | MCP-сервер: tools `list_datasets`, `get_dataset`, `find_stale_datasets`, `create_task` и resource `metadata://schema` |
| `agent.py` | Цикл агента: модель решает → вызов tool → результат идёт обратно в модель. Модель здесь заглушка `StubLLM` |

## Запуск

```bash
docker compose up -d            # Postgres с init.sql
pip install -r requirements.txt
python agent.py
```

Строка подключения берётся из `PG_DSN` (по умолчанию `postgresql://postgres:postgres@localhost:5432/metadata`).

Вывод (сокращённо):

```
-> find_stale_datasets({})
<- [customers (50 ч при SLA 24), finance_ledger (ни разу не грузился), web_events (3 ч при SLA 1)]
-> create_task({"dataset": "customers", "action": "reload", ...})
-> create_task({"dataset": "finance_ledger", "action": "notify_owner", ...})
-> create_task({"dataset": "web_events", "action": "reload", ...})

Создал задачи:
- #1 reload customers
- #2 notify_owner finance_ledger
- #3 reload web_events
```

## Как подключить настоящую модель

Замените `StubLLM.complete(messages, tools)` на вызов LLM: передайте `tools` (имя, описание и
JSON-схема из `list_tools()`) как определения инструментов, а из ответа модели соберите
`LLMResponse(tool_calls=[...])` или `LLMResponse(text=...)`. Цикл в `run_agent` менять не нужно.

Сервер можно подключить и к готовому MCP-клиенту (Claude Desktop, Claude Code, IDE):

```bash
claude mcp add pg-metadata -- python /path/to/server.py
```

## Почему нет tool «выполнить произвольный SQL»

Так задумано. Модель получает только узкие операции с параметризованными запросами,
поэтому не сможет сделать `DROP TABLE` или прочитать лишнее. Если нужен свободный SQL,
дайте серверу отдельного read-only пользователя БД.

Пример написан под `mcp` 2.x, где `FastMCP` переименован в `MCPServer`.
