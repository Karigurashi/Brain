"""Anthropic Claude Provider，底层使用 anthropic 官方 SDK。"""

from __future__ import annotations

import asyncio
import time
from dataclasses import replace
from typing import AsyncIterator, Iterator, Optional

import anthropic

from ..baseProvider import BaseProvider
from ..chatMessage import ChatChunk, ChatMessage, ChatResponse, TokenUsage, ToolSpec
from common.cancellationToken import CancellationToken
from ...llmConfig import LLMModel
from ...llmRequestParams import LLMRequestParams
from .anthropicProtocol import AnthropicProtocol


class AnthropicProvider(BaseProvider):
    """Anthropic Claude Messages API Provider。"""

    def __init__(self, model: LLMModel, **kwargs) -> None:
        super().__init__(model, **kwargs)
        self._thinkingBudget = model.thinkingBudget
        self._protocol = AnthropicProtocol()
        # SDK 层 max_retries=0：重试由框架层 BaseProvider._RetryCallCoreAsync 统一接管
        self._client = anthropic.Anthropic(
            base_url=self._model.url.rstrip("/"),
            api_key=self._model.apiKey,
            timeout=self._timeout,
            max_retries=0,
        )
        self._asyncClient = anthropic.AsyncAnthropic(
            base_url=self._model.url.rstrip("/"),
            api_key=self._model.apiKey,
            timeout=self._timeout,
            max_retries=0,
        )

    @property
    def providerName(self) -> str:
        return "anthropic"

    def Close(self) -> None:
        self._client.close()

    async def CloseAsync(self) -> None:
        await self._asyncClient.close()

    # ---- TokenUsage 提取 ----

    @staticmethod
    def _ExtractUsage(usage: object) -> Optional[TokenUsage]:
        if usage is None:
            return None
        inputTokens = getattr(usage, "input_tokens", 0)
        outputTokens = getattr(usage, "output_tokens", 0)
        return TokenUsage(
            promptTokens=inputTokens,
            completionTokens=outputTokens,
            totalTokens=inputTokens + outputTokens,
            cacheCreationInputTokens=getattr(usage, "cache_creation_input_tokens", 0) or 0,
            cacheReadInputTokens=getattr(usage, "cache_read_input_tokens", 0) or 0,
        )

    # ==================================================================
    #  同步 Invoke
    # ==================================================================

    def Invoke(
        self,
        messages: list[ChatMessage],
        requestParams: Optional[LLMRequestParams] = None,
    ) -> ChatResponse:
        rid = self._NewRequestId()
        t0 = time.monotonic()

        rp = requestParams or LLMRequestParams.DEFAULT
        thinkingBudget = rp.thinkingBudget or self._thinkingBudget
        if thinkingBudget != rp.thinkingBudget:
            rp = replace(rp, thinkingBudget=thinkingBudget)

        if rp.onBeforeRequest:
            rp.onBeforeRequest(messages)

        try:
            params = self._protocol.BuildRequestParams(
                messages, rp, stream=False,
                tools=rp.tools,
                modelName=self._model.modelName,
            )
            resp = self._client.messages.create(**params)

            textParts: list[str] = []
            thinkingParts: list[str] = []
            for block in resp.content:
                t = getattr(block, "type", "")
                if t == "text":
                    textParts.append(getattr(block, "text", ""))
                elif t == "thinking":
                    thinkingParts.append(getattr(block, "thinking", ""))

            usage = self._ExtractUsage(resp.usage)
            toolCalls = self._protocol.ParseToolCalls(resp.content)

            result = ChatResponse(
                content="\n".join(textParts),
                reasoningContent="\n".join(thinkingParts),
                model=resp.model,
                usage=usage,
                finishReason=getattr(resp, "stop_reason", "") or "",
                toolCalls=toolCalls,
            )

            self._AccumulateUsage(usage)
            self._LogSuccess(rid, "Invoke", t0, usage)

            if rp.onAfterRequest:
                rp.onAfterRequest(result)

            return result
        except Exception as exc:
            self._LogError(rid, "Invoke", t0, exc)
            self._RaiseLLMError(exc, onError=rp.onError)

    # ==================================================================
    #  同步 Stream
    # ==================================================================

    def Stream(
        self,
        messages: list[ChatMessage],
        requestParams: Optional[LLMRequestParams] = None,
    ) -> Iterator[ChatChunk]:
        rid = self._NewRequestId()
        t0 = time.monotonic()

        rp = requestParams or LLMRequestParams.DEFAULT
        thinkingBudget = rp.thinkingBudget or self._thinkingBudget
        if thinkingBudget != rp.thinkingBudget:
            rp = replace(rp, thinkingBudget=thinkingBudget)

        if rp.onBeforeRequest:
            rp.onBeforeRequest(messages)

        try:
            params = self._protocol.BuildRequestParams(
                messages, rp, stream=True,
                tools=rp.tools,
                modelName=self._model.modelName,
            )
            with self._client.messages.stream(**params) as stream:
                for event in stream:
                    etype = getattr(event, "type", "")

                    if etype == "content_block_delta":
                        delta = getattr(event, "delta", None)
                        if delta is None:
                            continue
                        dt = getattr(delta, "type", "")
                        if dt == "text_delta":
                            yield ChatChunk(content=getattr(delta, "text", ""))
                        elif dt == "thinking_delta":
                            yield ChatChunk(reasoningContent=getattr(delta, "thinking", ""))

                    elif etype == "message_delta":
                        usage = self._ExtractUsage(getattr(event, "usage", None))
                        if usage:
                            self._AccumulateUsage(usage)
                        fr = getattr(getattr(event, "delta", None), "stop_reason", "")
                        yield ChatChunk(usage=usage, finishReason=fr or "")

                    elif etype == "message_stop":
                        yield ChatChunk(finishReason="end_turn")

            self._LogSuccess(rid, "Stream", t0)
        except Exception as exc:
            self._LogError(rid, "Stream", t0, exc)
            self._RaiseLLMError(exc, onError=rp.onError)

    # ==================================================================
    #  异步 _InvokeCoreAsync（单次纯调用，重试由 BaseProvider 外层处理）
    # ==================================================================

    async def _InvokeCoreAsync(
        self,
        messages: list[ChatMessage],
        cancellationToken: Optional[CancellationToken] = None,
        requestParams: Optional[LLMRequestParams] = None,
    ) -> ChatResponse:
        rid = self._NewRequestId()
        t0 = time.monotonic()

        rp = requestParams or LLMRequestParams.DEFAULT
        thinkingBudget = rp.thinkingBudget or self._thinkingBudget
        if thinkingBudget != rp.thinkingBudget:
            rp = replace(rp, thinkingBudget=thinkingBudget)

        self._CheckCancellation(cancellationToken)

        if rp.onBeforeRequest:
            rp.onBeforeRequest(messages)

        try:
            params = self._protocol.BuildRequestParams(
                messages, rp, stream=False,
                tools=rp.tools,
                modelName=self._model.modelName,
            )
            resp = await self._InvokeWithTimeoutAsync(
                self._asyncClient.messages.create(**params),
            )

            textParts: list[str] = []
            thinkingParts: list[str] = []
            for block in resp.content:
                t = getattr(block, "type", "")
                if t == "text":
                    textParts.append(getattr(block, "text", ""))
                elif t == "thinking":
                    thinkingParts.append(getattr(block, "thinking", ""))

            usage = self._ExtractUsage(resp.usage)
            toolCalls = self._protocol.ParseToolCalls(resp.content)

            result = ChatResponse(
                content="\n".join(textParts),
                reasoningContent="\n".join(thinkingParts),
                model=resp.model,
                usage=usage,
                finishReason=getattr(resp, "stop_reason", "") or "",
                toolCalls=toolCalls,
            )

            self._AccumulateUsage(usage)
            self._LogSuccess(rid, "_InvokeCoreAsync", t0, usage)

            if rp.onAfterRequest:
                rp.onAfterRequest(result)

            return result
        except asyncio.CancelledError:
            self._LogCancelled(rid, "_InvokeCoreAsync")
            raise
        except Exception as exc:
            self._LogError(rid, "_InvokeCoreAsync", t0, exc)
            self._RaiseLLMError(exc, onError=rp.onError)

    # ==================================================================
    #  异步 _StreamCoreAsync（单次纯调用，重试由 BaseProvider 外层处理）
    # ==================================================================

    async def _StreamCoreAsync(
        self,
        messages: list[ChatMessage],
        cancellationToken: Optional[CancellationToken] = None,
        requestParams: Optional[LLMRequestParams] = None,
    ) -> AsyncIterator[ChatChunk]:
        rid = self._NewRequestId()
        t0 = time.monotonic()

        rp = requestParams or LLMRequestParams.DEFAULT
        thinkingBudget = rp.thinkingBudget or self._thinkingBudget
        if thinkingBudget != rp.thinkingBudget:
            rp = replace(rp, thinkingBudget=thinkingBudget)

        self._CheckCancellation(cancellationToken)

        if rp.onBeforeRequest:
            rp.onBeforeRequest(messages)

        try:
            params = self._protocol.BuildRequestParams(
                messages, rp, stream=True,
                tools=rp.tools,
                modelName=self._model.modelName,
            )
            cancelled = False
            async with self._asyncClient.messages.stream(**params) as stream:
                async for event in stream:
                    if cancellationToken and cancellationToken.IsCancellationRequested:
                        self._LogCancelled(rid, "_StreamCoreAsync")
                        cancelled = True
                        break

                    etype = getattr(event, "type", "")

                    if etype == "content_block_delta":
                        delta = getattr(event, "delta", None)
                        if delta is None:
                            continue
                        dt = getattr(delta, "type", "")
                        if dt == "text_delta":
                            yield ChatChunk(content=getattr(delta, "text", ""))
                        elif dt == "thinking_delta":
                            yield ChatChunk(reasoningContent=getattr(delta, "thinking", ""))

                    elif etype == "message_delta":
                        usage = self._ExtractUsage(getattr(event, "usage", None))
                        if usage:
                            self._AccumulateUsage(usage)
                        fr = getattr(getattr(event, "delta", None), "stop_reason", "")
                        yield ChatChunk(usage=usage, finishReason=fr or "")

                    elif etype == "message_stop":
                        yield ChatChunk(finishReason="end_turn")

            # async with 退出时自动关闭底层 SSE 连接，服务端收到 TCP FIN 停止生成
            if not cancelled:
                self._LogSuccess(rid, "_StreamCoreAsync", t0)
        except asyncio.CancelledError:
            self._LogCancelled(rid, "_StreamCoreAsync")
            raise
        except Exception as exc:
            self._LogError(rid, "_StreamCoreAsync", t0, exc)
            self._RaiseLLMError(exc, onError=rp.onError)
