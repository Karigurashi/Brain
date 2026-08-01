"""Delete/Cancel Task tool —— remove a scheduled task or cancel a running workflow."""

from __future__ import annotations

import json as _json

from ..baseTool import BaseTool
from ..eToolCategory import EToolCategory
from ..toolResult import ToolResult
from ..toolComponent import ToolComponent


@ToolComponent.Register
class DeleteTaskTool(BaseTool):
    """Delete a scheduled task (1) or cancel a running workflow (2)."""

    name: str = "deleteTask"
    description: str = "Delete/cancel task. Only when user asks."
    category: EToolCategory = EToolCategory.TASK
    parameters: dict = {
        "type": "object",
        "properties": {
            "taskId": {
                "type": "integer",
                "description": "Task ID to delete/cancel",
            },
            "taskType": {
                "type": "integer",
                "enum": [1, 2],
                "description": "1=SCHEDULED, 2=WORKFLOW",
            },
        },
        "required": ["taskId", "taskType"],
    }

    async def _InvokeAsync(self, taskId: int, taskType: int) -> ToolResult:
        return self._Invoke(taskId=taskId, taskType=taskType)

    def _Invoke(self, taskId: int, taskType: int) -> ToolResult:
        from agent.component.schedule.scheduleComponent import ScheduleComponent
        from agent.component.workflow.workflowComponent import WorkflowComponent

        if taskType == 1:
            scheduleComp = self._agent.GetComponent(ScheduleComponent)
            ok = scheduleComp.DeleteTask(taskId)
            if not ok:
                return ToolResult.Fail(f"Task '{taskId}' not found", toolName=self.name)
            result = {"taskId": taskId, "deleted": True}
            return ToolResult.Ok(
                content=_json.dumps(result, ensure_ascii=False),
                data=result,
                toolName=self.name,
            )

        if taskType == 2:
            workflowComp = self._agent.GetComponent(WorkflowComponent)
            ok = workflowComp.Cancel(taskId)
            if ok:
                return ToolResult.Ok(
                    content=_json.dumps({"taskId": taskId, "cancelled": True}, ensure_ascii=False),
                    toolName=self.name,
                )
            return ToolResult.Fail(
                f"Workflow '{taskId}' not found or not running",
                toolName=self.name,
            )

        return ToolResult.Fail(
            f"Unknown taskType '{taskType}'. Use 1(SCHEDULED) or 2(WORKFLOW).",
            toolName=self.name,
        )
