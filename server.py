"""MCP-сервер над Postgres с метаданными датасетов.

Сервер ничего не "решает" сам — он только даёт агенту инструменты:
читать метаданные и записывать решения в очередь задач.

Запуск (stdio, так его поднимает агент/IDE):
    python server.py
"""

import os
from typing import Any

import psycopg
from psycopg.rows import dict_row

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

DSN = os.getenv("PG_DSN", "postgresql://postgres:postgres@localhost:5432/metadata")

mcp = MCPServer(
    name="pg-metadata",
    instructions=(
        "Каталог метаданных датасетов в Postgres. "
        "Используй find_stale_datasets, чтобы найти просроченные данные, "
        "и create_task, чтобы поставить задачу на перезагрузку."
    ),
)


async def query(sql: str, *params: Any) -> list[dict[str, Any]]:
    """Маленький хелпер: одно соединение на запрос, строки как dict."""
    async with await psycopg.AsyncConnection.connect(DSN, row_factory=dict_row) as conn:
        cur = await conn.execute(sql, params)
        rows = await cur.fetchall() if cur.description else []
        return [{k: (v.isoformat() if hasattr(v, "isoformat") else v) for k, v in r.items()} for r in rows]


# --- Tools: то, что модель может вызывать ------------------------------------


@mcp.tool()
async def list_datasets(only_active: bool = True) -> list[dict[str, Any]]:
    """Список датасетов из каталога с владельцем, SLA свежести и временем последней загрузки."""
    return await query(
        """
        SELECT name, owner, freshness_sla_h, last_loaded_at, is_active
        FROM datasets
        WHERE is_active OR NOT %s
        ORDER BY name
        """,
        only_active,
    )


@mcp.tool()
async def get_dataset(name: str) -> dict[str, Any]:
    """Полные метаданные одного датасета по имени."""
    rows = await query("SELECT * FROM datasets WHERE name = %s", name)
    if not rows:
        raise ToolError(f"Датасет {name!r} не найден")
    return rows[0]


@mcp.tool()
async def find_stale_datasets() -> list[dict[str, Any]]:
    """Активные датасеты, у которых нарушен SLA свежести (или которые ни разу не грузились)."""
    return await query(
        """
        SELECT name, owner, freshness_sla_h, last_loaded_at,
               round(extract(epoch FROM now() - last_loaded_at) / 3600)::int AS hours_since_load
        FROM datasets
        WHERE is_active
          AND (last_loaded_at IS NULL
               OR last_loaded_at < now() - make_interval(hours => freshness_sla_h))
        ORDER BY name
        """
    )


@mcp.tool()
async def create_task(dataset: str, action: str, reason: str) -> dict[str, Any]:
    """Поставить задачу в очередь оркестратора.

    action: 'reload' — перезагрузить датасет, 'notify_owner' — уведомить владельца.
    """
    if action not in ("reload", "notify_owner"):
        raise ToolError("action должен быть 'reload' или 'notify_owner'")
    rows = await query(
        """
        INSERT INTO agent_tasks (dataset, action, reason)
        VALUES (%s, %s, %s)
        RETURNING id, dataset, action, status, created_at
        """,
        dataset,
        action,
        reason,
    )
    return rows[0]


# --- Resources: справочная информация, которую клиент может подложить в контекст ---


@mcp.resource("metadata://schema")
def schema() -> str:
    """Описание таблиц, чтобы модель понимала, с чем работает."""
    return (
        "datasets(name, owner, description, freshness_sla_h, last_loaded_at, is_active)\n"
        "agent_tasks(id, dataset, action, reason, status, created_at)"
    )


if __name__ == "__main__":
    mcp.run()  # stdio по умолчанию; для HTTP: mcp.run("streamable-http", port=8000)
