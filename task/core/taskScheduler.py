"""内部共享任务调度器。"""

from __future__ import annotations

import asyncio
from typing import Optional, TypeVar

from .baseScheduler import BaseScheduler
from .task import ETaskStatus, Task, TaskT
from .taskHandle import TaskDoneCallback, TaskHandle

DEFAULT_MAX_TASKS = 500

TTask = TypeVar("TTask", bound=Task)
TResult = TypeVar("TResult")


class TaskScheduler(BaseScheduler):
    """内部调度器：管理 ID 分配 + handle 注册 + asyncio 调度。"""

    def __init__(self, maxTasks: int = DEFAULT_MAX_TASKS) -> None:
        self._nextId: int = 1
        self._handles: dict[int, TaskHandle] = {}
        self._maxTasks: int = maxTasks

    def Schedule(
        self,
        task: TTask,
        onFinished: TaskDoneCallback | None = None,
    ) -> TaskHandle[TTask]:
        """调度一个已构造的任务，返回可等待/可取消的执行句柄。"""
        self._EnsureEventLoop()
        while len(self._handles) >= self._maxTasks:
            self._EvictLRU()

        def _Cleanup(handle: TaskHandle) -> None:
            if onFinished is not None:
                onFinished(handle)
            self._handles.pop(handle.task.info.taskId, None)

        handle = self._CreateHandle(task, _Cleanup)
        self._handles[task.info.taskId] = handle
        handle.asyncioTask = asyncio.create_task(self._ExecuteAsync(handle))
        return handle

    def AllocTaskId(self) -> int:
        """分配唯一 taskId。"""
        taskId = self._nextId
        self._nextId += 1
        return taskId

    def GetHandle(self, taskId: int) -> Optional[TaskHandle]:
        """按 taskId 获取执行句柄。"""
        handle = self._handles.get(taskId)
        if handle is not None:
            self._BumpAccess(handle)
        return handle

    def GetTask(self, taskId: int) -> Optional[Task]:
        """按 taskId 获取任务。"""
        handle = self._handles.get(taskId)
        if handle is not None:
            self._BumpAccess(handle)
            return handle.task
        return None

    def GetTaskT(self, taskId: int) -> Optional[TaskT[TResult]]:
        """按 taskId 获取带结果任务，类型安全下转。"""
        handle = self._handles.get(taskId)
        if handle is not None:
            self._BumpAccess(handle)
            if isinstance(handle.task, TaskT):
                return handle.task
        return None

    def ListTasks(self) -> list[Task]:
        """返回所有已调度任务。"""
        return [h.task for h in self._handles.values()]

    def Cancel(self, taskId: int) -> bool:
        """取消指定运行中任务。"""
        handle = self._handles.get(taskId)
        if handle is None:
            return False
        return handle.Cancel()

    def CancelAll(self) -> None:
        """取消所有已调度任务。"""
        for taskId in list(self._handles.keys()):
            self.Cancel(taskId)

    def _EvictLRU(self) -> None:
        if not self._handles:
            return
        doneHandles = {
            tid: h
            for tid, h in self._handles.items()
            if h.task.info.status != ETaskStatus.RUNNING
        }
        source = doneHandles if doneHandles else dict(self._handles)
        lruId = min(source, key=lambda tid: source[tid].lastAccessedAt)
        handle = self._handles.pop(lruId)
        if handle.asyncioTask is not None and not handle.asyncioTask.done():
            handle.asyncioTask.cancel()
        if handle.cancellationToken is not None:
            handle.cancellationToken.Cancel()
