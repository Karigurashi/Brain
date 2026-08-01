"""LoopComponent —— Agent 协程调度上下文：loop 归属校验 + Task 生命周期 + 跨线程入口。"""

from __future__ import annotations

import asyncio
import concurrent.futures
from typing import TYPE_CHECKING, Coroutine

from agent.core.baseComponent import BaseComponent

if TYPE_CHECKING:
    from agent.core.baseAgent import BaseAgent


class LoopComponent(BaseComponent):
    """Agent 协程调度上下文 —— 统一承载 Agent 内部全部协程调度行为。

    职责:
        1. loop 归属: 首次调度时捕获 running loop，后续严格校验一致性，
           跨 loop 立即 raise（单 Agent 单 loop 铁律的结构强制）。
        2. Task 生命周期: CreateTask 统一登记派生 Task，完成自动注销，
           OnDestroy 批量取消，杜绝孤儿 Task 在 Agent 销毁后继续运行。
        3. 跨线程入口: PostFromThread 封装 run_coroutine_threadsafe，
           是外部线程向 Agent 投递协程的唯一合法通道。

    不封装 asyncio.to_thread、sleep/wait_for/gather 等无 loop 归属语义的组合子。
    """

    def OnInitialize(self, agent: BaseAgent) -> None:
        self._agent: BaseAgent = agent
        self._loop: asyncio.AbstractEventLoop | None = None
        self._runLock: asyncio.Lock | None = None
        self._tasks: set[asyncio.Task] = set()

    def OnDestroy(self) -> None:
        """取消全部登记的派生 Task。"""
        for task in self._tasks:
            task.cancel()
        self._tasks.clear()

    # ---- 运行锁 ----

    @property
    def runLock(self) -> asyncio.Lock:
        """Agent 运行互斥锁 —— 惰性创建，绑定所属 loop。

        首次访问时完成 loop 捕获；此后在其他 loop 中访问立即 raise。
        """
        self._BindLoop()
        if self._runLock is None:
            self._runLock = asyncio.Lock()
        return self._runLock

    # ---- 协程调度 ----

    def CreateTask(self, coro: Coroutine) -> asyncio.Task:
        """在 Agent 所属 loop 创建并登记派生 Task。

        必须在 Agent 所属 loop 内调用（running loop 与绑定 loop 一致），
        否则 raise。Task 完成时自动注销；OnDestroy 时统一取消未完成 Task。

        Args:
            coro: 待调度协程。

        Returns:
            新创建的 asyncio.Task。
        """
        self._BindLoop()
        task = asyncio.create_task(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return task

    def PostFromThread(self, coro: Coroutine) -> concurrent.futures.Future:
        """从外部线程向 Agent loop 投递协程 —— 唯一合法跨线程通道。

        要求 Agent 已在所属 loop 中运行过（loop 已绑定）。

        Args:
            coro: 待投递协程。

        Returns:
            concurrent.futures.Future，可跨线程等待结果。

        Raises:
            RuntimeError: Agent 尚未在任何事件循环中运行。
        """
        if self._loop is None:
            raise RuntimeError(
                "LoopComponent: Agent 尚未在任何事件循环中运行，无法跨线程投递"
            )
        return asyncio.run_coroutine_threadsafe(coro, self._loop)

    # ---- 内部 ----

    def _BindLoop(self) -> None:
        """首次调用捕获 running loop；后续校验一致性，跨 loop 立即 raise。

        Raises:
            RuntimeError: 当前线程无 running loop，或当前 loop 与绑定 loop 不一致。
        """
        try:
            current = asyncio.get_running_loop()
        except RuntimeError:
            raise RuntimeError(
                "LoopComponent: 协程调度必须在运行中的事件循环内进行"
            ) from None
        if self._loop is None:
            self._loop = current
        elif self._loop is not current:
            raise RuntimeError(
                "LoopComponent: Agent 实例禁止跨事件循环调度协程"
            )
