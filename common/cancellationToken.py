"""协作式取消令牌，用于安全中断异步调用及跨线程 CPU 密集型操作。

---- 设计背景：Python asyncio vs C# Task ----

Python asyncio 是单线程事件循环模型，与 C# 的 Task + ThreadPool 多线程模型本质不同：

    C# 多线程异步：
        每个 Task 可能被调度到不同线程，底层用 IOCP 等 OS 级通知，
        跨线程取消通过 CancellationTokenSource + volatile + 内存屏障保证安全。

    Python asyncio 单线程协程：
        所有协程跑在同一个事件循环线程上，底层 I/O 同样是 OS 级非阻塞
        (httpx.AsyncClient 使用 epoll/IOCP，是真正的异步 I/O，不是线程池伪异步)。
        没有"开专门线程发 HTTP"这个概念——是"告诉 OS 盯着 socket，有数据了叫我"。

关键结论：
- await 只能在事件循环所在的那个线程使用，不能跨线程直接 await。
- 跨线程取消协程的正确姿势：子线程调 Cancel() → 主线程事件循环在下一个协程切换点检测。
- CPython 中 GIL 保护下，跨线程调 asyncio.Event.set() 碰巧安全，但 Python 规范不承诺。

---- 使用场景 ----

1. 协程内取消（InvokeAsync / StreamAsync）：

    token = CancellationToken()
    task = asyncio.create_task(client.StreamAsync(..., cancellationToken=token))
    # 用户点击取消按钮
    token.Cancel()  # 事件循环在下一个 chunk 产出前退出流式循环

2. 跨线程取消（子线程调 Cancel，主线程事件循环跑协程）：

    # 后台线程想取消主线程的 LLM 请求
    def CancelFromOtherThread(token, mainLoop):
        token.Cancel()  # CPython 下 GIL 保护，实际可用

    更严格的写法：通过 loop.call_soon_threadsafe 将取消操作丢回事件循环：
        asyncio.run_coroutine_threadsafe(_CancelAsync(token), mainLoop)

3. CPU 密集型后处理 + 协作式取消：

    LLM 返回后的 AST 解析、代码分析、报告生成等 CPU 密集操作应通过
    asyncio.to_thread() 扔到线程池，避免阻塞事件循环。同时将 token 传入
    线程函数实现协作式取消：

        async def ReviewFile(client, content, token):
            # I/O 密集：等 AI，协程中 await
            aiResult = await client.StreamAsync(content, cancellationToken=token)
            # CPU 密集：扔线程池，token 带进去
            report = await asyncio.to_thread(HeavyAnalysis, aiResult, token)

        def HeavyAnalysis(aiResult, token):
            for file in aiResult.files:
                token.ThrowIfCancellationRequested()  # 检查取消，提前退出
                ast = parseAst(file)
                report = generateReport(ast)
                saveToDb(report)

    注意：asyncio.to_thread 的 await 可以因取消而抛异常，
    但子线程不会立即被杀死——它只是不再等待结果。
    线程函数内部必须主动检查 token，才能真正中断 CPU 运算。
    这和 C# 的 CancellationToken 协作式取消逻辑完全一致。
"""

from __future__ import annotations

import asyncio


class CancelledError(Exception):
    """取消信号触发的异常。"""

    pass


class CancellationToken:
    """基于 asyncio.Event 的协作式取消令牌。

    使用方式::

        # 协程中
        token = CancellationToken()
        task = asyncio.create_task(someStreamAsync(..., cancellationToken=token))
        token.Cancel()  # 信号通知取消

        # 跨线程取消
        def ThreadFunc(token, mainLoop):
            token.Cancel()

        # 线程函数中协作式取消
        def HeavyWork(data, token):
            for item in data:
                token.ThrowIfCancellationRequested()
                process(item)

        await asyncio.to_thread(HeavyWork, data, token)
    """

    __slots__ = ("_event",)

    def __init__(self) -> None:
        self._event = asyncio.Event()

    @property
    def IsCancellationRequested(self) -> bool:
        """是否已发出取消信号。

        协程和线程函数均可安全调用此属性来轮询取消状态。
        在 CPython 中受 GIL 保护，跨线程读取也是安全的。
        """
        return self._event.is_set()

    def Cancel(self) -> None:
        """发出取消信号，触发所有等待方停止迭代。

        可在任意线程中调用。在 CPython 中，asyncio.Event.set() 受 GIL
        保护，跨线程调用碰巧安全。若需严格遵循 asyncio 规范，请通过
        asyncio.run_coroutine_threadsafe() 将取消操作调度到事件循环线程。
        """
        self._event.set()

    def Reset(self) -> None:
        """重置取消信号（复用令牌时使用）。

        注意：仅应在确认所有消费方都已停止后调用，否则可能丢失取消信号。
        """
        self._event.clear()

    def ThrowIfCancellationRequested(self) -> None:
        """检查取消状态，若已取消则抛出 CancelledError。

        设计为在 CPU 密集型线程函数中配合使用，让线程在循环迭代间
        主动响应取消信号：:

            def HeavyWork(data, token):
                for item in data:
                    token.ThrowIfCancellationRequested()
                    process(item)
        """
        if self._event.is_set():
            raise CancelledError("Operation cancelled by CancellationToken")
