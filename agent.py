"""Простейший агент: MCP-клиент + цикл "модель -> tool call -> результат -> модель".

Вместо настоящей LLM стоит StubLLM с захардкоженной логикой. Интерфейс у неё
такой же, как был бы у обёртки над реальной моделью: на вход история сообщений
и список инструментов, на выход — либо вызовы инструментов, либо финальный текст.

Запуск:
    python agent.py
"""

import asyncio
import json
import os
import sys
from dataclasses import dataclass, field
from typing import Any

from mcp import Client
from mcp.client.stdio import StdioServerParameters


@dataclass
class ToolCall:
    name: str
    arguments: dict[str, Any]


@dataclass
class LLMResponse:
    text: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)


class StubLLM:
    """Заглушка модели. Заменить на вызов реальной LLM с тем же интерфейсом.

    Настоящая модель получила бы `tools` (имя, описание, JSON-схема аргументов)
    и сама решила бы, что вызвать. Здесь решение зашито правилами.
    """

    async def complete(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> LLMResponse:
        last = messages[-1]

        # 1. Пришла задача от пользователя -> сначала смотрим, что просрочено.
        if last["role"] == "user":
            return LLMResponse(tool_calls=[ToolCall("find_stale_datasets", {})])

        # 2. Получили список просроченных -> решаем, что делать с каждым.
        if last["role"] == "tool" and last["name"] == "find_stale_datasets":
            calls = []
            for ds in last["content"]:
                if ds["last_loaded_at"] is None:
                    # Ни разу не грузился — перезагрузка не поможет, нужен человек.
                    calls.append(ToolCall("create_task", {
                        "dataset": ds["name"],
                        "action": "notify_owner",
                        "reason": f"Датасет ни разу не загружался, владелец {ds['owner']}",
                    }))
                else:
                    calls.append(ToolCall("create_task", {
                        "dataset": ds["name"],
                        "action": "reload",
                        "reason": f"Не обновлялся {ds['hours_since_load']} ч при SLA {ds['freshness_sla_h']} ч",
                    }))
            if not calls:
                return LLMResponse(text="Все активные датасеты свежие, делать ничего не нужно.")
            return LLMResponse(tool_calls=calls)

        # 3. Задачи созданы -> отчитываемся.
        created = [m["content"] for m in messages if m["role"] == "tool" and m["name"] == "create_task"]
        lines = [f"- #{t['id']} {t['action']} {t['dataset']}" for t in created]
        return LLMResponse(text="Создал задачи:\n" + "\n".join(lines))


def tool_result_to_python(result) -> Any:
    """Достаём из CallToolResult данные: structured_content, иначе текст."""
    if result.is_error:
        return {"error": " ".join(c.text for c in result.content if c.type == "text")}
    if result.structured_content is not None:
        # Для функций, возвращающих не-dict, MCPServer заворачивает ответ в {"result": ...}
        return result.structured_content.get("result", result.structured_content)
    return " ".join(c.text for c in result.content if c.type == "text")


async def run_agent(task: str, max_steps: int = 10) -> str:
    server = StdioServerParameters(
        command=sys.executable,
        args=[os.path.join(os.path.dirname(os.path.abspath(__file__)), "server.py")],
        env=dict(os.environ),  # пробрасываем PG_DSN и прочее
    )
    llm = StubLLM()

    async with Client(server) as client:
        # Схема инструментов в том виде, в каком её отдали бы реальной модели.
        tools = [
            {"name": t.name, "description": t.description, "input_schema": t.input_schema}
            for t in (await client.list_tools()).tools
        ]
        print("Инструменты сервера:", [t["name"] for t in tools])

        messages: list[dict[str, Any]] = [{"role": "user", "content": task}]

        for _ in range(max_steps):
            response = await llm.complete(messages, tools)

            if not response.tool_calls:
                return response.text or ""

            messages.append({"role": "assistant", "tool_calls": response.tool_calls})
            for call in response.tool_calls:
                print(f"-> {call.name}({json.dumps(call.arguments, ensure_ascii=False)})")
                result = await client.call_tool(call.name, call.arguments)
                data = tool_result_to_python(result)
                print(f"<- {json.dumps(data, ensure_ascii=False, default=str)}")
                messages.append({"role": "tool", "name": call.name, "content": data})

    return "Превышен лимит шагов"


if __name__ == "__main__":
    answer = asyncio.run(run_agent("Проверь свежесть данных и поставь задачи на просроченные датасеты"))
    print("\n" + answer)
