"""BaseScheduler —— Task 调度器公共执行生命周期。"""

from __future__ import annotations

import asyncio
import time
from typing import TypeVar

from common.cancellationToken import CancellationToken
from common.logger import Logger
from .task import ETaskStatus, Task
from .taskHandle import TaskDoneCallback, TaskHandle

TTask = TypeVar("TTask", bound=Task)


class BaseScheduler:
    """调度器基类：只负责 TaskHandle 生命周期和协程执行。"""

    def _CreateHandle(
        self,
        task: TTask,
        onFinished: TaskDoneCallback | None = None,
    ) -> TaskHandle[TTask]:
        token = CancellationToken()
        task.info.status = ETaskStatus.RUNNING
        return TaskHandle(
            task=task,
            scheduler=self,
            cancellationToken=token,
            onFinished=onFinished,
        )

    def _CancelHandle(self, handle: TaskHandle) -> bool:
        task = handle.task
        if task.info.status != ETaskStatus.RUNNING:
            return False
        task.info.status = ETaskStatus.CANCELLED
        self._OnHandleCancel(handle)
        if handle.cancellationToken is not None:
            handle.cancellationToken.Cancel()
        if handle.asyncioTask is not None and not handle.asyncioTask.done():
            handle.asyncioTask.cancel()
        self._BumpAccess(handle)
        return True

    async def _WaitHandleAsync(self, handle: TaskHandle) -> None:
        if handle.asyncioTask is None:
            raise RuntimeError(f"Task {handle.task.info.taskId} has no underlying asyncio task")
        await handle.asyncioTask
        self._BumpAccess(handle)

    async def _ExecuteAsync(self, handle: TaskHandle) -> None:
        await self._ExecuteCoreAsync(handle)
        self._NotifyFinished(handle)

    async def _ExecuteCoreAsync(self, handle: TaskHandle) -> None:
        task = handle.task
        try:
            await task._Execute(handle.cancellationToken)
            if task.info.status == ETaskStatus.RUNNING:
                task.info.status = ETaskStatus.COMPLETED
        except asyncio.CancelledError:
            if task.info.status == ETaskStatus.RUNNING:
                task.info.status = ETaskStatus.CANCELLED
        except Exception as e:
            if task.info.status == ETaskStatus.RUNNING:
                task.info.status = ETaskStatus.FAILED
            Logger.Error(f"Task {task.info.taskId} ({task.info.name}) failed: {e}")

    def _NotifyFinished(self, handle: TaskHandle) -> None:
        if handle.onFinished is None:
            return
        handle.onFinished(handle)
        handle.onFinished = None

    def _OnHandleCancel(self, handle: TaskHandle) -> None:
        """取消 handle 时的派生类清理点。"""
        pass

    @staticmethod
    def _EnsureEventLoop() -> None:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            raise RuntimeError(
                "Task runtime requires a running event loop. "
                "Ensure asyncio.run() or equivalent is active."
            )

    @staticmethod
    def _BumpAccess(handle: TaskHandle) -> None:
        handle.lastAccessedAt = time.time()
