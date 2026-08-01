"""ScheduleComponent —— Agent 侧定时任务组件。"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING, Optional

from agent.component.data.dataComponent import DataComponent
from agent.component.injection.injectionComponent import InjectionComponent
from agent.core.baseComponent import BaseComponent
from task.schedule.taskSpec import TaskSpec

from .scheduleRegistry import ScheduleRegistry

if TYPE_CHECKING:
    from agent.core.baseAgent import BaseAgent


class ScheduleComponent(BaseComponent):
    """管理定时任务：ScheduleRegistry（CronScheduler + JSON 持久化）+ 回注。"""

    def OnInitialize(self, agent: BaseAgent) -> None:
        self._agent: BaseAgent = agent

        dataComp = agent.GetComponent(DataComponent)
        self._registry = ScheduleRegistry(dataComp.config.tasksDir)
        self._injectComp = agent.GetComponent(InjectionComponent)

        self._registry.RestoreAll(self._OnFire)

    def OnDestroy(self) -> None:
        self._registry.Clear()

    # ---- 对外 API ----

    def CreateScheduleTask(self, name: str, expression: str, prompt: str) -> TaskSpec:
        """创建定时任务：校验 → 持久化 → arm。"""
        return self._registry.CreateAgentWake(name, expression, prompt, self._OnFire)

    def DeleteTask(self, specId: int) -> bool:
        """按 specId 取消 cron 并删除持久化定义。"""
        return self._registry.RemoveSpec(specId)

    def Cancel(self, specId: int) -> bool:
        """取消定时任务（同 DeleteTask）。"""
        return self.DeleteTask(specId)

    def GetSpec(self, specId: int) -> Optional[TaskSpec]:
        return self._registry.GetSpec(specId)

    def ListSpecs(self) -> list[TaskSpec]:
        return self._registry.ListSpecs()

    # ---- 内部 ----

    def _OnFire(self, spec: TaskSpec) -> None:
        """Cron 到点回调：更新统计 + 持久化 + 注入 prompt。"""
        spec.lastFiredAt = time.time()
        spec.fireCount += 1
        self._registry.Persist()

        if not spec.prompt:
            return
        lines = [
            "<task_schedule>",
            f"Name: {spec.name or 'Scheduled'}",
            spec.prompt,
            "</task_schedule>",
        ]
        content = "\n".join(lines)
        self._injectComp.InjectAsync(content)
