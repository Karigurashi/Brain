"""OpenAI 兼容 Provider，底层使用 openai 官方 SDK。

支持 GPT-4 / GPT-3.5 / DeepSeek / Ollama / vLLM 等所有
兼容 /chat/completions 协议的端点。
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import AsyncIterator, Iterator, Optional

import openai

from ..baseProvider import BaseProvider
from ..chatMessage import ChatChunk, ChatMessage, ChatResponse, TokenUsage, ToolCall, ToolSpec
from common.cancellationToken import CancellationToken
from ...llmConfig import LLMModel
from ...llmRequestParams import LLMRequestParams
from .openaiProtocol import OpenAIProtocol


class OpenAIProvider(BaseProvider):
    """OpenAI 兼容 Provider，封装 openai 官方 SDK。"""

    def __init__(self, model: LLMModel, **kwargs) -> None:
        super().__init__(model, **kwargs)
        self._protocol = OpenAIProtocol()
        # SDK 层 max_retries=0：重试由框架层 BaseProvider._RetryCallCoreAsync 统一接管
        self._client = openai.OpenAI(
            base_url=self._model.url.rstrip("/"),
            api_key=self._model.apiKey,
            timeout=self._timeout,
            max_retries=0,
        )
        self._asyncClient = openai.AsyncOpenAI(
            base_url=self._model.url.rstrip("/"),
            api_key=self._model.apiKey,
            timeout=self._timeout,
            max_retries=0,
        )

    @property
    def providerName(self) -> str:
        return "openai"

    def Close(self) -> None:
        self._client.close()

    async def CloseAsync(self) -> None:
        await self._asyncClient.close()

    # ---- TokenUsage 提取 ----

    @staticmethod
    def _ExtractUsage(usage: object) -> Optional[TokenUsage]:
        if usage is None:
            return None
        promptDetails = getattr(usage, "prompt_tokens_details", None)
        cachedTokens = getattr(promptDetails, "cached_tokens", 0) or 0 if promptDetails else 0
        return TokenUsage(
            promptTokens=getattr(usage, "prompt_tokens", 0),
            completionTokens=getattr(usage, "completion_tokens", 0),
            totalTokens=getattr(usage, "total_tokens", 0),
            cacheReadInputTokens=cachedTokens,
        )

    # ---- 流式工具调用分片拼装 ----

    @staticmethod
    def _ParseStreamToolCalls(
        deltaToolCalls: list,
        accumulator: dict[int, dict],
    ) -> Optional[list[ToolCall]]:
        """累加 delta.tool_calls 分片，当所有分片到齐后返回完整 ToolCall 列表。

        OpenAI 流式协议中，工具调用按 delta 分片返回：
          chunk1: delta.tool_calls[0] = { id, function: { name, arguments: "" } }
          chunk2: delta.tool_calls[0] = { function: { arguments: '{"qu' } }
          ...
          chunkN: finish_reason = "tool_calls"

        拼装逻辑：按 index 累加 id / name / arguments，在流结束时一次性返回。
        """
        for tc in deltaToolCalls:
            idx = getattr(tc, "index", 0)
            if idx not in accumulator:
                accumulator[idx] = {"id": "", "name": "", "arguments": ""}
            entry = accumulator[idx]
            tcId = getattr(tc, "id", None)
            if tcId:
                entry["id"] = tcId
            func = getattr(tc, "function", None)
            if func:
                fName = getattr(func, "name", None)
                if fName:
                    entry["name"] = fName
                fArgs = getattr(func, "arguments", None)
                if fArgs:
                    entry["arguments"] += fArgs
        return None

    @staticmethod
    def _BuildAccumulatedToolCalls(accumulator: dict[int, dict]) -> list[ToolCall]:
        """将累加完成的分片拼装为 ToolCall 列表。"""
        if not accumulator:
            return []
        result: list[ToolCall] = []
        for idx in sorted(accumulator):
            entry = accumulator[idx]
            try:
                args = json.loads(entry["arguments"]) if entry["arguments"] else {}
            except (json.JSONDecodeError, TypeError):
                args = {}
            result.append(ToolCall(
                id=entry["id"],
                name=entry["name"],
                arguments=args if isinstance(args, dict) else {},
            ))
        return result

    # ---- reasoning_content 提取 ----

    @staticmethod
    def _ExtractReasoning(message: object) -> str:
        extra = getattr(message, "model_extra", None) or {}
        return extra.get("reasoning_content", "") or ""

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

        if rp.onBeforeRequest:
            rp.onBeforeRequest(messages)

        try:
            params = self._protocol.BuildRequestParams(
                messages, rp, stream=False,
                tools=rp.tools,
                modelName=self._model.modelName,
            )
            resp = self._client.chat.completions.create(**params)

            choice = resp.choices[0]
            content = choice.message.content or ""
            reasoningContent = self._ExtractReasoning(choice.message)
            usage = self._ExtractUsage(resp.usage)
            toolCalls = self._protocol.ParseToolCalls(choice)

            result = ChatResponse(
                content=content,
                reasoningContent=reasoningContent,
                model=resp.model or self._model.modelName,
                usage=usage,
                finishReason=choice.finish_reason or "",
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

        if rp.onBeforeRequest:
            rp.onBeforeRequest(messages)

        try:
            params = self._protocol.BuildRequestParams(
                messages, rp, stream=True,
                tools=rp.tools,
                modelName=self._model.modelName,
            )
            stream = self._client.chat.completions.create(**params)

            toolCallAccumulator: dict[int, dict] = {}

            for chunk in stream:
                usage = None
                if getattr(chunk, "usage", None) is not None:
                    usage = self._ExtractUsage(chunk.usage)
                    self._AccumulateUsage(usage)

                if not chunk.choices:
                    if usage:
                        yield ChatChunk(usage=usage)
                    continue

                choice = chunk.choices[0]
                delta = choice.delta
                content = delta.content or "" if delta else ""
                reasoningContent = self._ExtractReasoning(delta) if delta else ""

                # 累加流式工具调用分片
                if delta and getattr(delta, "tool_calls", None):
                    self._ParseStreamToolCalls(delta.tool_calls, toolCallAccumulator)

                finishReason = choice.finish_reason or ""

                # 流结束时输出拼装好的完整工具调用
                toolCalls = None
                if finishReason == "tool_calls" and toolCallAccumulator:
                    toolCalls = self._BuildAccumulatedToolCalls(toolCallAccumulator)
                    toolCallAccumulator = {}

                cc = ChatChunk(
                    content=content,
                    reasoningContent=reasoningContent,
                    usage=usage,
                    finishReason=finishReason,
                    index=choice.index or 0,
                    toolCalls=toolCalls,
                )
                if not cc.isEmpty:
                    yield cc

            self._LogSuccess(rid, "Stream", t0, self._totalUsage)
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
                self._asyncClient.chat.completions.create(**params),
            )

            choice = resp.choices[0]
            content = choice.message.content or ""
            reasoningContent = self._ExtractReasoning(choice.message)
            usage = self._ExtractUsage(resp.usage)
            toolCalls = self._protocol.ParseToolCalls(choice)

            result = ChatResponse(
                content=content,
                reasoningContent=reasoningContent,
                model=resp.model or self._model.modelName,
                usage=usage,
                finishReason=choice.finish_reason or "",
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

        self._CheckCancellation(cancellationToken)

        if rp.onBeforeRequest:
            rp.onBeforeRequest(messages)

        try:
            stream = None
            cancelled = False
            try:
                params = self._protocol.BuildRequestParams(
                    messages, rp, stream=True,
                    tools=rp.tools,
                    modelName=self._model.modelName,
                )
                stream = await self._asyncClient.chat.completions.create(**params)

                toolCallAccumulator: dict[int, dict] = {}

                async for chunk in stream:
                    if cancellationToken and cancellationToken.IsCancellationRequested:
                        self._LogCancelled(rid, "StreamAsync")
                        cancelled = True
                        break

                    usage = None
                    if getattr(chunk, "usage", None) is not None:
                        usage = self._ExtractUsage(chunk.usage)
                        self._AccumulateUsage(usage)

                    if not chunk.choices:
                        if usage:
                            yield ChatChunk(usage=usage)
                        continue

                    choice = chunk.choices[0]
                    delta = choice.delta
                    content = delta.content or "" if delta else ""
                    reasoningContent = self._ExtractReasoning(delta) if delta else ""

                    # 累加流式工具调用分片
                    if delta and getattr(delta, "tool_calls", None):
                        self._ParseStreamToolCalls(delta.tool_calls, toolCallAccumulator)

                    finishReason = choice.finish_reason or ""

                    # 流结束时输出拼装好的完整工具调用
                    toolCalls = None
                    if finishReason == "tool_calls" and toolCallAccumulator:
                        toolCalls = self._BuildAccumulatedToolCalls(toolCallAccumulator)
                        toolCallAccumulator = {}

                    cc = ChatChunk(
                        content=content,
                        reasoningContent=reasoningContent,
                        usage=usage,
                        finishReason=finishReason,
                        index=choice.index or 0,
                        toolCalls=toolCalls,
                    )
                    if not cc.isEmpty:
                        yield cc

                if not cancelled:
                    self._LogSuccess(rid, "_StreamCoreAsync", t0, self._totalUsage)
            finally:
                # 主动关闭底层 HTTP 连接，确保服务端收到 TCP RST 立即停止生成
                if stream is not None:
                    await stream.close()
        except asyncio.CancelledError:
            self._LogCancelled(rid, "_StreamCoreAsync")
            raise
        except Exception as exc:
            self._LogError(rid, "_StreamCoreAsync", t0, exc)
            self._RaiseLLMError(exc, onError=rp.onError)
