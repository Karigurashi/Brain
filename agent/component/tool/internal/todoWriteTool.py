"""TodoWrite 工具 —— 创建和管理任务列表。

LLM 自主拆解任务 → 写入 StatusBar → 每轮自动渲染到上下文末尾。
框架不干预拆解逻辑，仅提供写入接口。
"""

from __future__ import annotations

from agent.component.contex.eContextLodLevel import EContextLodLevel
from agent.component.harness import ETodoStatus, HarnessComponent, TodoItem

from ..baseTool import BaseTool, EToolParallelMode
from ..eToolCategory import EToolCategory
from ..toolResult import ToolResult
from ..toolComponent import ToolComponent


@ToolComponent.Register
class TodoWriteTool(BaseTool):
    """创建和管理任务列表，用于跟踪复杂多步骤任务。
    """

    name: str = "todoWrite"
    description: str = "Create and manage a task list for complex multi-step tasks"
    parallelMode: EToolParallelMode = EToolParallelMode.SAFE
    resultLodLevel = EContextLodLevel.DISCARDABLE
    category: EToolCategory = EToolCategory.INTERNAL
    parameters: dict = {
        "type": "object",
        "properties": {
            "todos": {
                "type": "array",
                "description": "Todo items array",
                "items": {
                    "type": "object",
                    "properties": {
                        "content": {
                            "type": "string",
                            "description": "Task description",
                        },
                        "status": {
                            "type": "string",
                            "enum": [s.value for s in ETodoStatus],
                            "description": "pending, in_progress, completed, cancelled",
                        },
                    },
                    "required": ["content", "status"],
                },
            },
        },
        "required": ["todos"],
    }

    def _Invoke(self, todos: list[dict]) -> ToolResult:
        if not isinstance(todos, list):
            return ToolResult.Fail("'todos' must be a list", toolName=self.name)

        validNames = {s.value for s in ETodoStatus}
        for i, item in enumerate(todos):
            if not isinstance(item, dict):
                return ToolResult.Fail(
                    f"todos[{i}] must be an object", toolName=self.name,
                )
            if item.get("status") not in validNames:
                return ToolResult.Fail(
                    f"todos[{i}].status '{item.get('status')}' invalid, "
                    f"must be one of: {', '.join(sorted(validNames))}",
                    toolName=self.name,
                )

        active = [
            TodoItem(content=item["content"], status=ETodoStatus(item["status"]))
            for item in todos
            if item["status"] in (ETodoStatus.PENDING.value, ETodoStatus.IN_PROGRESS.value)
        ]
        harness = self._agent.GetComponent(HarnessComponent)
        harness.UpdateTodos(active)

        lines = [f"Updated {len(todos)} todo(s):"]
        for i, t in enumerate(todos, 1):
            lines.append(f"  [{i}] {t['content']} ({t['status']})")
        return ToolResult.Ok(
            "\n".join(lines),
            toolName=self.name,
        )
