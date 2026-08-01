"""Create Task tool —— schedule an AgentWake cron task persisted as JSON."""

from __future__ import annotations

import json as _json

from agent.component.schedule.scheduleComponent import ScheduleComponent

from ..baseTool import BaseTool
from ..eToolCategory import EToolCategory
from ..toolResult import ToolResult
from ..toolComponent import ToolComponent


@ToolComponent.Register
class CreateScheduleTaskTool(BaseTool):
    """Create a scheduled Agent-wake task (cron + prompt), persist to tasksDir."""

    name: str = "createScheduleTask"
    description: str = "Create a scheduled task."
    category: EToolCategory = EToolCategory.TASK
    parameters: dict = {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "Task name",
            },
            "expression": {
                "type": "string",
                "description": "Cron expression, e.g. '0 9 * * *'",
            },
            "prompt": {
                "type": "string",
                "description": "Prompt to inject on fire",
            },
        },
        "required": ["name", "expression", "prompt"],
    }

    async def _InvokeAsync(self, name: str, expression: str, prompt: str) -> ToolResult:
        if not expression.strip():
            return ToolResult.Fail("expression is required", toolName=self.name)
        if not prompt.strip():
            return ToolResult.Fail("prompt is required", toolName=self.name)

        scheduleComp = self._agent.GetComponent(ScheduleComponent)
        try:
            spec = scheduleComp.CreateScheduleTask(
                name=name.strip(),
                expression=expression.strip(),
                prompt=prompt.strip(),
            )
        except Exception as exc:
            return ToolResult.Fail(
                f"Failed to create task: {exc}",
                toolName=self.name,
            )

        result = {
            "taskId": spec.specId,
            "name": spec.name,
            "expression": spec.expression,
        }
        return ToolResult.Ok(
            content=_json.dumps(result, ensure_ascii=False),
            data=result,
            toolName=self.name,
        )
