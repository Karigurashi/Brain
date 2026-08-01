"""LLM 抽象接口，对标 LangChain BaseLanguageModel / Runnable。

所有 Provider 必须实现此接口，保证 LLMManager 可统一调度。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import AsyncIterator, Iterator, Optional

from common.cancellationToken import CancellationToken
from .provider.chatMessage import ChatChunk, ChatMessage, ChatResponse, TokenUsage, ToolSpec
from .llmRequestParams import LLMRequestParams


class BaseLLM(ABC):
    """大模型抽象基类，定义同步/异步、流式/非流式四维调用接口。

    对标 LangChain Runnable::

        Invoke      → invoke
        Stream      → stream
        InvokeAsync → ainvoke
        StreamAsync → astream
    """

    # ———— 元信息 ————

    @property
    @abstractmethod
    def providerName(self) -> str:
        """Provider 标识，如 'openai'、'anthropic'、'gemini'。"""
        ...

    @property
    @abstractmethod
    def modelName(self) -> str:
        """当前使用的模型名。"""
        ...

    # ———— 同步接口 ————

    @abstractmethod
    def Invoke(
        self,
        messages: list[ChatMessage],
        requestParams: Optional[LLMRequestParams] = None,
    ) -> ChatResponse:
        """同步非流式调用，返回完整响应。"""
        ...

    @abstractmethod
    def Stream(
        self,
        messages: list[ChatMessage],
        requestParams: Optional[LLMRequestParams] = None,
    ) -> Iterator[ChatChunk]:
        """同步流式调用，逐块产出增量。"""
        ...

    # ———— 异步接口 ————

    @abstractmethod
    async def InvokeAsync(
        self,
        messages: list[ChatMessage],
        cancellationToken: Optional[CancellationToken] = None,
        requestParams: Optional[LLMRequestParams] = None,
    ) -> ChatResponse:
        """异步非流式调用，支持通过 CancellationToken 取消。"""
        ...

    @abstractmethod
    async def StreamAsync(
        self,
        messages: list[ChatMessage],
        cancellationToken: Optional[CancellationToken] = None,
        requestParams: Optional[LLMRequestParams] = None,
    ) -> AsyncIterator[ChatChunk]:
        """异步流式调用，支持通过 CancellationToken 在 chunk 间取消。"""
        ...

    # ———— 工具绑定 ————

    @abstractmethod
    def BindTools(self, tools: list[ToolSpec]) -> None:
        """绑定工具列表，后续调用自动携带。"""
        ...

    # ———— Token 计数（可选） ————

    def CountTokens(self, messages: list[ChatMessage]) -> int:
        """估算消息的 token 数，默认用字符数/4 粗略估算。"""
        total = 0
        for msg in messages:
            total += len(msg.content) // 4
        return total

    # ———— 累计用量 ————

    @property
    def totalUsage(self) -> TokenUsage:
        """累计 Token 用量。

        默认返回空 TokenUsage()。Provider 子类（BaseProvider）应覆盖此属性，
        维护 _totalUsage 字段并在每次调用后累加。
        """
        return TokenUsage()

    def ResetUsage(self) -> None:
        """重置累计用量。

        默认无操作。Provider 子类（BaseProvider）应覆盖此方法，
        将 _totalUsage 重置为 TokenUsage()。
        """
        pass
