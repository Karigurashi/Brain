"""TaskHandle —— 单次任务执行句柄。"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Callable, Generic, Optional, Protocol, TypeVar, overload

if TYPE_CHECKING:
    from common.cancellationToken import CancellationToken
    from .task import Task, TaskT

TTask = TypeVar("TTask", bound="Task")
TResult = TypeVar("TResult")
TaskDoneCallback = Callable[["TaskHandle"], None]


class TaskHandleScheduler(Protocol):
    def _CancelHandle(self, handle: "TaskHandle") -> bool:
        ...

    async def _WaitHandleAsync(self, handle: "TaskHandle") -> None:
        ...


@dataclass(slots=True)
class TaskHandle(Generic[TTask]):
    """可等待、可取消的单次任务执行句柄。"""

    task: TTask
    scheduler: TaskHandleScheduler
    asyncioTask: asyncio.Task | None = None
    cancellationToken: Optional["CancellationToken"] = None
    onFinished: TaskDoneCallback | None = None
    lastAccessedAt: float = field(default_factory=time.time)

    @property
    def taskId(self) -> int:
        return self.task.info.taskId

    def GetTask(self) -> TTask:
        """获取此句柄持有的泛型 Task。"""
        return self.task

    def Cancel(self) -> bool:
        """请求取消此任务。"""
        return self.scheduler._CancelHandle(self)

    @overload
    async def WaitAsync(self: "TaskHandle[TaskT[TResult]]") -> TResult:
        ...

    @overload
    async def WaitAsync(self) -> None:
        ...

    async def WaitAsync(self) -> object | None:
        """等待此任务完成；TaskT 会返回强类型结果。"""
        await self.scheduler._WaitHandleAsync(self)
        from .task import TaskT
        if isinstance(self.task, TaskT):
            return self.task.result
        return None

    def __await__(self):
        return self.WaitAsync().__await__()
