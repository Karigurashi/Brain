"""List Tasks tool —— list Agent-owned tasks, optionally filtered by type."""

from __future__ import annotations

import json as _json
import time

from ..baseTool import BaseTool, EToolParallelMode
from ..eToolCategory import EToolCategory
from ..toolResult import ToolResult
from ..toolComponent import ToolComponent


@ToolComponent.Register
class ListTasksTool(BaseTool):
    """List background tasks with status and results.

    Optional taskType filters by SCHEDULED / WORKFLOW.
    Omit taskType to list all tasks owned by this Agent.
    """

    name: str = "listTasks"
    description: str = "List tasks. Only when user asks."
    category: EToolCategory = EToolCategory.TASK
    parallelMode: EToolParallelMode = EToolParallelMode.SAFE
    parameters: dict = {
        "type": "object",
        "properties": {
            "taskType": {
                "type": "integer",
                "enum": [1, 2],
                "description": "1=SCHEDULED, 2=WORKFLOW; omit to list all",
            },
        },
        "required": [],
    }

    _lastCallTime: float = 0.0
    _lastCallTaskType: int | None = None
    _RATE_LIMIT_SECONDS: float = 5.0

    async def _InvokeAsync(self, taskType: int | None = None) -> ToolResult:
        return self._Invoke(taskType=taskType)

    def _Invoke(self, taskType: int | None = None) -> ToolResult:
        """Return task statuses with optional type filter and rate-limit protection."""
        from agent.component.data.dataComponent import DataComponent
        from agent.component.schedule.scheduleComponent import ScheduleComponent
        from agent.component.workflow.workflowComponent import WorkflowComponent

        now = time.time()
        elapsed = now - self._lastCallTime
        if elapsed < self._RATE_LIMIT_SECONDS and self._lastCallTaskType == taskType:
            return ToolResult.Fail(
                f"已限频，请{self._RATE_LIMIT_SECONDS:.0f}s后再试。",
                toolName=self.name,
            )
        self._lastCallTime = now
        self._lastCallTaskType = taskType

        filterType: int | None = None
        if taskType is not None:
            if taskType == 1:
                filterType = 1
            elif taskType == 2:
                filterType = 2
            else:
                return ToolResult.Fail(
                    f"Unknown taskType '{taskType}'. Use 1(SCHEDULED) or 2(WORKFLOW).",
                    toolName=self.name,
                )

        dataComp = self._agent.GetComponent(DataComponent)
        items: list[dict] = []

        if filterType is None or filterType == 2:
            workflowComp = self._agent.GetComponent(WorkflowComponent)
            for task in workflowComp.ListTasks():
                info = task.info
                item: dict = {
                    "taskId": info.taskId,
                    "name": info.name,
                    "taskType": "WORKFLOW",
                    "status": info.status.name,
                    "createdAt": int(info.createdAt),
                }
                items.append(item)

        if filterType is None or filterType == 1:
            if dataComp.config.enableSchedule:
                scheduleComp = self._agent.GetComponent(ScheduleComponent)
                for spec in scheduleComp.ListSpecs():
                    items.append({
                        "taskId": spec.specId,
                        "name": spec.name,
                        "taskType": "SCHEDULED",
                        "status": "ACTIVE",
                        "expression": spec.expression,
                        "prompt": spec.prompt,
                    })

        return ToolResult.Ok(
            content=_json.dumps(items, ensure_ascii=False, indent=2),
            data=items,
            toolName=self.name,
        )
