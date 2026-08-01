"""Task —— 可执行任务，包装 async 协程的执行句柄。

Task 不可被继承（对标 C# sealed Task），所有工作以协程工厂注入。
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from enum import IntEnum
from typing import TYPE_CHECKING, Any, Callable, Coroutine, Generic, Optional, TypeVar, cast

if TYPE_CHECKING:
    from common.cancellationToken import CancellationToken

TResult = TypeVar("TResult")

CoroFunc = Callable[["CancellationToken | None"], Coroutine[Any, Any, None]]
CoroFuncT = Callable[["CancellationToken | None"], Coroutine[Any, Any, "TResult"]]


class ETaskStatus(IntEnum):
    """任务运行时状态。"""

    RUNNING = 0
    COMPLETED = 1
    FAILED = 2
    CANCELLED = 3


@dataclass(slots=True)
class TaskInfo:
    """任务的通用身份与一次执行状态。"""

    taskId: int
    createdAt: float
    name: str = "Unnamed"
    status: ETaskStatus = ETaskStatus.RUNNING


class Task:
    """不可被继承的任务，包装一个 async 协程。

    Task 本身不包含调度逻辑，由调度器创建并管理生命周期。
    """

    def __init__(self, coro: CoroFunc, taskId: int, name: str = "") -> None:
        self._coro: CoroFunc = coro
        self._info: TaskInfo = TaskInfo(
            taskId=taskId,
            createdAt=time.time(),
            name=name or "Unnamed",
        )

    @property
    def info(self) -> TaskInfo:
        return self._info

    async def _Execute(self, cancellationToken: Optional["CancellationToken"] = None) -> None:
        """内部执行入口，由调度器调用。"""
        await self._coro(cancellationToken)


class TaskT(Task, Generic[TResult]):
    """类似 C# Task<T> 的带结果任务，不可被继承。"""

    def __init__(self, coro: CoroFuncT, taskId: int, name: str = "") -> None:
        super().__init__(coro, taskId=taskId, name=name)
        self._hasResult: bool = False
        self._result: TResult | None = None

    @property
    def result(self) -> TResult:
        if not self._hasResult:
            raise RuntimeError(f"Task {self.info.taskId} has not produced a result")
        return cast(TResult, self._result)

    async def _Execute(self, cancellationToken: Optional["CancellationToken"] = None) -> None:
        self._result = await cast(CoroFuncT, self._coro)(cancellationToken)
        self._hasResult = True
