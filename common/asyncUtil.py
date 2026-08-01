"""异步工具集 —— 提供 async generator 同步桥接、超时保护等通用能力。

不依赖任何业务模块，可被 Agent / Workflow / 任何需要同步消费异步生成器的场景复用。
"""

from __future__ import annotations

import asyncio
import queue as _queue
import threading
import time as _time

from typing import AsyncIterator, Iterator


def RunAsyncGenerator(
    coro: AsyncIterator,
    timeout: float | None = None,
) -> Iterator:
    """在事件循环中运行 async generator，逐条 yield 事件。

    自动检测当前是否已有运行中的事件循环：
    - 无运行循环：创建新事件循环（标准 CLI 场景）。
    - 已有运行循环：在独立线程中创建新事件循环执行（Web 服务器 / Jupyter 场景），
      避免 RuntimeError 或 run_coroutine_threadsafe 同线程死锁。

    Args:
        coro: 异步生成器协程。
        timeout: 最大执行秒数，None 表示不限。超时后抛出 TimeoutError。

    Yields:
        异步生成器产生的每个事件。
    """
    try:
        asyncio.get_running_loop()
        hasRunningLoop = True
    except RuntimeError:
        hasRunningLoop = False

    if hasRunningLoop:
        # 已有事件循环：独立线程跑事件循环，用线程安全队列实时跨线程传递事件，
        # 边产生边 yield（真流式），不再先缓冲全部事件再回放。
        eventQueue: "_queue.Queue" = _queue.Queue()
        sentinel = object()
        exceptionHolder: list = []

        def _RunInThread():
            threadLoop = asyncio.new_event_loop()
            asyncio.set_event_loop(threadLoop)

            async def _Drain():
                async for event in coro:
                    eventQueue.put(event)

            try:
                threadLoop.run_until_complete(_Drain())
            except Exception as exc:
                exceptionHolder.append(exc)
            finally:
                threadLoop.close()
                eventQueue.put(sentinel)

        thread = threading.Thread(target=_RunInThread, daemon=True)
        thread.start()

        # 超时守卫：使用逐段 get 替代无限阻塞
        deadline = None
        if timeout is not None and timeout > 0:
            deadline = _time.monotonic() + timeout

        while True:
            remaining = None
            if deadline is not None:
                remaining = deadline - _time.monotonic()
                if remaining <= 0:
                    # 超时：中断线程中的事件循环，迫使协程退出
                    threadLoop.call_soon_threadsafe(threadLoop.stop)
                    thread.join(timeout=5.0)
                    raise TimeoutError(
                        f"Async generator exceeded timeout of {timeout:.1f}s"
                    )
            try:
                item = eventQueue.get(timeout=max(remaining, 0.1) if remaining is not None else None)
            except _queue.Empty:
                continue
            if item is sentinel:
                break
            yield item

        thread.join()
        if exceptionHolder:
            raise exceptionHolder[0]
    else:
        loop = asyncio.new_event_loop()
        try:
            gen = coro.__aiter__()
            while True:
                try:
                    if timeout is not None and timeout > 0:
                        event = loop.run_until_complete(
                            asyncio.wait_for(gen.__anext__(), timeout=timeout)
                        )
                    else:
                        event = loop.run_until_complete(gen.__anext__())
                    yield event
                except StopAsyncIteration:
                    break
                except asyncio.TimeoutError:
                    raise TimeoutError(
                        f"Async generator exceeded timeout of {timeout:.1f}s"
                    )
        finally:
            loop.close()
