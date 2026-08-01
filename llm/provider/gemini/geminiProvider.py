"""Google Gemini Provider，底层使用 google-genai 官方 SDK。"""

from __future__ import annotations

import asyncio
import time
from typing import AsyncIterator, Iterator, Optional

from ..baseProvider import BaseProvider
from ..chatMessage import ChatChunk, ChatMessage, ChatResponse, TokenUsage, ToolSpec
from common.cancellationToken import CancellationToken
from ...llmConfig import LLMModel
from ...llmRequestParams import LLMRequestParams
from .geminiProtocol import GeminiProtocol


class GeminiProvider(BaseProvider):
    """Google Gemini Provider，封装 google-genai SDK。"""

    def __init__(self, model: LLMModel, **kwargs) -> None:
        super().__init__(model)
        self._protocol = GeminiProtocol()
        self._client = None
        self._asyncClient = None
        self._clientKwargs: dict = {
            "api_key": self._model.apiKey,
            "http_options": {
                "timeout": int(self._timeout * 1000),
            },
        }
        # 注：google-genai SDK 的 maxRetries 行为因版本而异，
        # 框架层通过 _InvokeWithTimeoutAsync 提供额外的超时保护

    def _GetClient(self):
        if self._client is None:
            from google import genai
            self._client = genai.Client(**self._clientKwargs)
        return self._client

    def _GetAsyncClient(self):
        if self._asyncClient is None:
            from google import genai
            self._asyncClient = genai.Client(**self._clientKwargs)
        return self._asyncClient

    @property
    def providerName(self) -> str:
        return "gemini"

    def Close(self) -> None:
        pass  # genai Client 无显式 close

    async def CloseAsync(self) -> None:
        pass

    # ---- TokenUsage 提取 ----

    @staticmethod
    def _ExtractUsage(usageMetadata: object) -> Optional[TokenUsage]:
        if usageMetadata is None:
            return None
        return TokenUsage(
            promptTokens=getattr(usageMetadata, "prompt_token_count", 0),
            completionTokens=getattr(usageMetadata, "candidates_token_count", 0),
            totalTokens=getattr(usageMetadata, "total_token_count", 0),
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

        if rp.onBeforeRequest:
            rp.onBeforeRequest(messages)

        try:
            params = self._protocol.BuildRequestParams(
                messages, rp, stream=False,
                tools=rp.tools,
                modelName=self._model.modelName,
            )
            model = params.pop("model")
            config = params.pop("config", {})
            contents = params.pop("contents")

            resp = self._GetClient().models.generate_content(
                model=model, contents=contents, config=config,
            )

            text = resp.text or ""
            usage = self._ExtractUsage(getattr(resp, "usage_metadata", None))
            toolCalls = self._protocol.ParseToolCalls(getattr(resp, "candidates", []))

            result = ChatResponse(
                content=text,
                model=self._model.modelName,
                usage=usage,
                finishReason=str(getattr(getattr(resp, "candidates", [{}])[0], "finish_reason", "")) if getattr(resp, "candidates", None) else "",
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
            model = params.pop("model")
            config = params.pop("config", {})
            contents = params.pop("contents")

            stream = self._GetClient().models.generate_content_stream(
                model=model, contents=contents, config=config,
            )

            for chunk in stream:
                text = chunk.text or ""
                usage = self._ExtractUsage(getattr(chunk, "usage_metadata", None))
                if usage:
                    self._AccumulateUsage(usage)

                cc = ChatChunk(content=text, usage=usage)
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
            model = params.pop("model")
            config = params.pop("config", {})
            contents = params.pop("contents")

            resp = await self._InvokeWithTimeoutAsync(
                self._GetAsyncClient().aio.models.generate_content(
                    model=model, contents=contents, config=config,
                ),
            )

            text = resp.text or ""
            usage = self._ExtractUsage(getattr(resp, "usage_metadata", None))
            toolCalls = self._protocol.ParseToolCalls(getattr(resp, "candidates", []))

            result = ChatResponse(
                content=text,
                model=self._model.modelName,
                usage=usage,
                finishReason=str(getattr(getattr(resp, "candidates", [{}])[0], "finish_reason", "")) if getattr(resp, "candidates", None) else "",
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
            params = self._protocol.BuildRequestParams(
                messages, rp, stream=True,
                tools=rp.tools,
                modelName=self._model.modelName,
            )
            model = params.pop("model")
            config = params.pop("config", {})
            contents = params.pop("contents")

            stream = None
            cancelled = False
            try:
                stream = await self._GetAsyncClient().aio.models.generate_content_stream(
                    model=model, contents=contents, config=config,
                )

                async for chunk in stream:
                    if cancellationToken and cancellationToken.IsCancellationRequested:
                        self._LogCancelled(rid, "_StreamCoreAsync")
                        cancelled = True
                        break

                    text = chunk.text or ""
                    usage = self._ExtractUsage(getattr(chunk, "usage_metadata", None))
                    if usage:
                        self._AccumulateUsage(usage)

                    cc = ChatChunk(content=text, usage=usage)
                    if not cc.isEmpty:
                        yield cc

                if not cancelled:
                    self._LogSuccess(rid, "_StreamCoreAsync", t0, self._totalUsage)
            finally:
                # 主动关闭底层 gRPC 流，通知服务端取消生成
                if stream is not None and hasattr(stream, 'aclose'):
                    await stream.aclose()
        except asyncio.CancelledError:
            self._LogCancelled(rid, "_StreamCoreAsync")
            raise
        except Exception as exc:
            self._LogError(rid, "_StreamCoreAsync", t0, exc)
            self._RaiseLLMError(exc, onError=rp.onError)
