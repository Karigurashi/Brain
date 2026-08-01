"""Provider 抽象基类。

连接池、重试、超时由官方 SDK 接管，框架层额外提供：
- InvokeAsync / StreamAsync 内置指数退避重试（由 settings.json maxRetries 控制，0=不重试）
- CancellationToken 取消机制
- asyncio.wait_for 超时包装（双重保险）
- asyncio.CancelledError 清理处理
- Token 累计、结构化日志。

子类仅需实现 _InvokeCoreAsync / _StreamCoreAsync（单次纯调用），
重试由本层 InvokeAsync / StreamAsync 统一处理。
"""

from __future__ import annotations

import asyncio
import time
import uuid
from abc import abstractmethod
from typing import AsyncIterator, Iterator, Optional, Callable

from common.llmError import LLMError
from common.logger import Logger

from ..baseLLM import BaseLLM
from ..llmRequestParams import LLMRequestParams
from common.cancellationToken import CancellationToken, CancelledError
from ..llmConfig import LLMModel
from .chatMessage import ChatChunk, ChatMessage, ChatResponse, TokenUsage


class BaseProvider(BaseLLM):
    """Provider 抽象基类。

    子类负责对接具体 SDK（openai / anthropic / gemini），
    实现 Invoke / Stream / _InvokeCoreAsync / _StreamCoreAsync。

    本层统一提供 InvokeAsync / StreamAsync（内置指数退避重试）、
    取消检查、超时包装、用量累积和结构化日志。
    """

    def __init__(
        self,
        model: LLMModel,
        timeout: float = 120.0,
        maxRetries: int = 3,
        retryBaseDelay: float = 1.0,
        retryMaxDelay: float = 30.0,
    ) -> None:
        self._model = model
        self._timeout = timeout
        self._maxRetries = maxRetries
        self._retryBaseDelay = retryBaseDelay
        self._retryMaxDelay = retryMaxDelay

        # 累计用量
        self._totalUsage = TokenUsage()

    # ———— 元信息 ————
    @property
    @abstractmethod
    def providerName(self) -> str:
        """Provider 标识，如 'openai'、'anthropic'。"""
        ...

    @property
    def modelName(self) -> str:
        return self._model.modelName

    # ———— 工具绑定 ————

    def BindTools(self, tools: list) -> None:
        """工具绑定由 LLMComponent 通过 LLMRequestParams 统一管理，Provider 层无需实现。"""
        pass

    # ———— 资源清理 ————
    def Close(self) -> None:
        """关闭底层 SDK 客户端（同步）。"""
        pass

    async def CloseAsync(self) -> None:
        """关闭底层 SDK 客户端（异步）。"""
        pass

    # ———— Token 累计 ————
    @property
    def totalUsage(self) -> TokenUsage:
        return self._totalUsage

    def ResetUsage(self) -> None:
        self._totalUsage = TokenUsage()

    def _AccumulateUsage(self, usage: Optional[TokenUsage]) -> None:
        if usage:
            self._totalUsage = self._totalUsage + usage

    # ———— 结构化日志 ————
    @staticmethod
    def _NewRequestId() -> str:
        return uuid.uuid4().hex[:8]

    def _LogSuccess(
        self, rid: str, method: str, t0: float, usage: Optional[TokenUsage] = None,
    ) -> None:
        durS = (time.monotonic() - t0)
        if usage is None:
            Logger.Info(
                "rid=%s %s %s/%s dur=%.1fs",
                rid, method, self.providerName, self._model.modelName, durS,
            )
            return
        promptK = usage.promptTokens / 1000.0
        completionK = usage.completionTokens / 1000.0
        cacheHitRate = round(usage.cacheReadInputTokens / usage.promptTokens * 100, 1) if usage.promptTokens > 0 else 0.0
        cacheCreateK = usage.cacheCreationInputTokens / 1000.0 if usage.cacheCreationInputTokens > 0 else 0.0
        cacheInfo = ""
        if usage.cacheReadInputTokens > 0:
            cacheInfo = f" cache_hit={cacheHitRate}%"
        if usage.cacheCreationInputTokens > 0:
            cacheInfo += f" cache_create={cacheCreateK:.1f}k"
        Logger.Info(
            "rid=%s %s %s/%s dur=%.1fs tokens_in=%.1fk tokens_out=%.1fk%s",
            rid, method, self.providerName, self._model.modelName,
            durS, promptK, completionK, cacheInfo,
        )

    def _LogError(
        self, rid: str, method: str, t0: float, exc: Exception,
    ) -> None:
        durS = (time.monotonic() - t0)
        Logger.Error(
            "rid=%s %s %s/%s dur=%.1fs error=%s",
            rid, method, self.providerName, self._model.modelName,
            durS, str(exc)[:200],
        )

    def _RaiseLLMError(
        self, exc: Exception,
        onError: Optional[Callable[[Exception], None]] = None,
    ) -> None:
        """统一转换为 LLMError。

        Args:
            exc: 原始异常。
            onError: 请求级异常回调（来自 LLMRequestParams.onError）。
        """
        if onError:
            onError(exc)
        raise LLMError(
            str(exc),
            provider=self.providerName, model=self._model.modelName,
        ) from exc

    # ———— 取消检查与超时包装 ————

    @staticmethod
    def _CheckCancellation(token: Optional[CancellationToken]) -> None:
        """检查取消令牌，若已取消则抛出 LLMError。"""
        if token is not None and token.IsCancellationRequested:
            raise LLMError("Request cancelled by CancellationToken")

    async def _InvokeWithTimeoutAsync(self, coro, timeout: Optional[float] = None) -> object:
        """用 asyncio.wait_for 包装异步调用，超时抛出 LLMError。

        与 SDK 内置 timeout 形成双重保险：SDK timeout 控制单次 HTTP 请求，
        本层 timeout 控制整个调用生命周期（含重试时间）。
        """
        timeout = timeout if timeout is not None else self._timeout
        try:
            return await asyncio.wait_for(coro, timeout=timeout)
        except asyncio.TimeoutError:
            raise LLMError(
                f"Request timed out after {timeout}s",
                provider=self.providerName, model=self._model.modelName,
            )

    @staticmethod
    def _LogCancelled(rid: str, method: str) -> None:
        """记录取消事件日志。"""
        Logger.Info("rid=%s %s CANCELLED by token", rid, method)

    # ———— 异步调用（内置指数退避重试） ————

    async def InvokeAsync(
        self,
        messages: list[ChatMessage],
        cancellationToken: Optional[CancellationToken] = None,
        requestParams: Optional[LLMRequestParams] = None,
    ) -> ChatResponse:
        """异步非流式调用，内置指数退避重试。

        重试行为由 settings.json 的 maxRetries 控制：设为 0 则不重试，
        直接委托给子类 _InvokeCoreAsync。
        """
        async for chunk in self._RetryCallCoreAsync(
            messages, cancellationToken, requestParams, streaming=False
        ):
            return ChatResponse(
                content=chunk.content or "",
                toolCalls=chunk.toolCalls,
                usage=chunk.usage,
            )

    async def StreamAsync(
        self,
        messages: list[ChatMessage],
        cancellationToken: Optional[CancellationToken] = None,
        requestParams: Optional[LLMRequestParams] = None,
    ) -> AsyncIterator[ChatChunk]:
        """异步流式调用，内置指数退避重试。

        重试行为由 settings.json 的 maxRetries 控制：设为 0 则不重试，
        直接委托给子类 _StreamCoreAsync。
        """
        async for chunk in self._RetryCallCoreAsync(
            messages, cancellationToken, requestParams, streaming=True
        ):
            yield chunk

    # ———— 子类实现的纯调用（不含重试） ————

    @abstractmethod
    async def _InvokeCoreAsync(
        self,
        messages: list[ChatMessage],
        cancellationToken: Optional[CancellationToken],
        requestParams: Optional[LLMRequestParams],
    ) -> ChatResponse:
        """单次异步非流式调用，由具体 Provider 实现。

        不包含重试逻辑，重试由外层 InvokeAsync 统一处理。
        """
        ...

    @abstractmethod
    async def _StreamCoreAsync(
        self,
        messages: list[ChatMessage],
        cancellationToken: Optional[CancellationToken],
        requestParams: Optional[LLMRequestParams],
    ) -> AsyncIterator[ChatChunk]:
        """单次异步流式调用，由具体 Provider 实现。

        不包含重试逻辑，重试由外层 StreamAsync 统一处理。
        """
        ...

    # ———— 重试核心 ————

    async def _RetryCallCoreAsync(
        self,
        messages: list[ChatMessage],
        cancellationToken: Optional[CancellationToken],
        requestParams: Optional[LLMRequestParams],
        streaming: bool,
    ) -> AsyncIterator[ChatChunk]:
        """指数退避重试循环，maxRetries=0 时退化为单次直调。"""
        lastException: Exception | None = None

        for attempt in range(self._maxRetries + 1):
            try:
                if streaming:
                    async for chunk in self._StreamCoreAsync(
                        messages, cancellationToken, requestParams,
                    ):
                        yield chunk
                else:
                    response = await self._InvokeCoreAsync(
                        messages, cancellationToken, requestParams,
                    )
                    yield ChatChunk(
                        content=response.content,
                        toolCalls=response.toolCalls,
                        usage=response.usage,
                    )
                return  # 成功，退出重试循环

            except LLMError as exc:
                lastException = exc
                if not self._IsRetryable(exc):
                    raise

            except asyncio.CancelledError:
                raise

            except (asyncio.TimeoutError, ConnectionError, OSError) as exc:
                # 仅网络/IO 层异常可重试，编程错误（AttributeError 等）必须立即暴露
                lastException = exc

            # 最后一轮不再等待
            if attempt >= self._maxRetries:
                break

            # 检查取消
            if cancellationToken is not None and cancellationToken.IsCancellationRequested:
                raise CancelledError("LLM call cancelled by user during retry backoff")

            delay = min(self._retryBaseDelay * (2 ** attempt), self._retryMaxDelay)
            Logger.Warning(
                f"LLM call failed, attempt {attempt + 1}/{self._maxRetries + 1}, "
                f"retrying in {delay:.1f}s: {lastException}"
            )
            await asyncio.sleep(delay)

            # 等待后再次检查取消
            if cancellationToken is not None and cancellationToken.IsCancellationRequested:
                raise CancelledError("LLM call cancelled by user during retry backoff")

        raise LLMError(
            f"LLM call exhausted all {self._maxRetries + 1} retry attempts: {lastException}"
        )

    @staticmethod
    def _IsRetryable(error: LLMError) -> bool:
        """判断 LLMError 是否可重试。

        可重试：429 (Rate Limit)、5xx (Server Error)、网络无状态码。
        不可重试：400、401、403、404 等客户端错误。
        """
        if error.statusCode is None:
            return True
        return error.statusCode in (429, 500, 502, 503, 504)
