"""WorkflowComponent —— Agent 侧 workflow 后台任务组件。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from agent.core.baseComponent import BaseComponent
from agent.component.injection.injectionComponent import InjectionComponent
from task.core import TaskScheduler
from task.core.task import TaskT
from task.core.taskHandle import TaskHandle
from task.workflow.workflow import Workflow
from task.workflow.workflowResult import WorkflowResult

if TYPE_CHECKING:
    from agent.core.baseAgent import BaseAgent


class WorkflowComponent(BaseComponent):
    """管理 Workflow 的提交、取消和结果查询。"""

    def OnInitialize(self, agent: BaseAgent) -> None:
        self._agent: BaseAgent = agent
        self._scheduler = TaskScheduler()
        self._injectComp = agent.GetComponent(InjectionComponent)

    def OnDestroy(self) -> None:
        self._scheduler.CancelAll()

    def AddTask(self, wf: Workflow) -> TaskT[WorkflowResult]:
        """提交 Workflow 为后台 Task 并返回 Task 句柄。"""
        taskId = self._scheduler.AllocTaskId()
        task = TaskT(wf.ExecuteAsync, taskId, name=wf.name)
        self._scheduler.Schedule(task, self._OnTaskFinished)
        return task

    def Cancel(self, taskId: int) -> bool:
        """取消指定运行中 workflow。"""
        return self._scheduler.Cancel(taskId)

    def GetTask(self, taskId: int) -> Optional[TaskT[WorkflowResult]]:
        return self._scheduler.GetTaskT(taskId)

    def GetTaskResult(self, taskId: int) -> WorkflowResult | None:
        task = self._scheduler.GetTaskT(taskId)
        if task is not None and task._hasResult:
            return task.result
        return None

    def ListTasks(self) -> list[TaskT[WorkflowResult]]:
        return self._scheduler.ListTasks()  # type: ignore[return-value]

    def FormatTaskResult(self, taskId: int) -> str | None:
        result = self.GetTaskResult(taskId)
        if result is None:
            return None
        return result.ToJson()

    # ---- 内部 ----

    def _OnTaskFinished(self, handle: TaskHandle[TaskT[WorkflowResult]]) -> None:
        """Workflow 完成回调：落盘结果，推送到 Agent 主循环。"""
        task = handle.task
        result: WorkflowResult = task.result
        content = result.GetLastEventMessage()
        if not content:
            return

        from agent.component.store.storeComponent import StoreComponent
        storeComp = self._agent.GetComponent(StoreComponent)
        storePath = storeComp.Store(result.ToJson())

        lines = [
            "<task_flow>",
            f"Name: {task.info.name}",
            content,
        ]
        if storePath:
            lines.append(f"Store: {storePath}")
        lines.append("</task_flow>")
        msg = "\n".join(lines)
        self._injectComp.InjectAsync(msg)
