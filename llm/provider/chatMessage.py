"""LLM 对话消息与响应数据模型，对标 LangChain Message / Anthropic Messages API。"""

from __future__ import annotations

import json

from dataclasses import dataclass, field
from typing import Optional

from common.const import ERole


# ==================== Tool ====================


@dataclass(slots=True)
class ToolSpec:
    """工具定义，用于描述可被模型调用的函数。

    Attributes:
        name: 工具名称。
        description: 工具描述。
        parameters: JSON Schema 格式的参数定义。
    """

    name: str
    description: str
    parameters: dict = field(default_factory=dict)


@dataclass(slots=True)
class ToolCall:
    """模型发起的工具调用。

    Attributes:
        id: 调用唯一标识。
        name: 工具名称。
        arguments: 调用参数（已解析为 dict）。
    """

    id: str
    name: str
    arguments: dict = field(default_factory=dict)


# ==================== 消息 ====================


@dataclass(slots=True)
class ChatMessage:
    """单条对话消息，兼容 OpenAI / Anthropic / Gemini 格式。

    Attributes:
        role: ERole 枚举值
        content: 文本内容（简单场景）或 ContentBlock 列表（多模态场景）。
        thinkingContent: 思考链（GLM / DeepSeek 等，序列化为 reasoning_content）。
        toolCalls: assistant 发起的工具调用列表。
        toolCallId: tool 角色消息对应的调用 ID。
    """

    role: ERole
    content: str
    thinkingContent: str = ""
    toolCalls: Optional[list[ToolCall]] = None
    toolCallId: str = ""

    # ---- 协议缓存（惰性初始化，避免高频调用重复分配 dict）----
    _cacheOpenAI: Optional[dict] = field(default=None, init=False, repr=False)
    _cacheAnthropic: Optional[dict] = field(default=None, init=False, repr=False)

    def InvalidateCache(self) -> None:
        """清除协议缓存。当 role/content/thinkingContent/toolCalls/toolCallId 被修改后必须调用。"""
        self._cacheOpenAI = None
        self._cacheAnthropic = None

    def ToOpenAI(self) -> dict:
        if self._cacheOpenAI is not None:
            return self._cacheOpenAI
        result: dict = {"role": self.role, "content": self.content}
        if self.thinkingContent:
            result["reasoning_content"] = self.thinkingContent
        if self.toolCalls:
            result["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.name,
                        "arguments": json.dumps(tc.arguments, ensure_ascii=False),
                    },
                }
                for tc in self.toolCalls
            ]
        if self.toolCallId:
            result["tool_call_id"] = self.toolCallId
        self._cacheOpenAI = result
        return result

    def ToAnthropic(self) -> dict:
        """转为 Anthropic 消息格式。"""
        if self._cacheAnthropic is not None:
            return self._cacheAnthropic
        self._cacheAnthropic = {"role": self.role, "content": self.content}
        return self._cacheAnthropic

    @staticmethod
    def System(content: str) -> ChatMessage:
        return ChatMessage(role=ERole.SYSTEM, content=content)

    @staticmethod
    def User(content: str) -> ChatMessage:
        return ChatMessage(role=ERole.USER, content=content)

    @staticmethod
    def Assistant(content: str) -> ChatMessage:
        return ChatMessage(role=ERole.ASSISTANT, content=content)

    @staticmethod
    def Tool(content: str, toolCallId: str = "") -> ChatMessage:
        return ChatMessage(role=ERole.TOOL, content=content, toolCallId=toolCallId)


# ==================== Token 用量 ====================

@dataclass(slots=True)
class TokenUsage:
    """单次调用的 Token 消耗统计。

    Attributes:
        promptTokens: 输入 token 数。
        completionTokens: 输出 token 数。
        totalTokens: 总计。
        cacheCreationInputTokens: Prompt Caching 首次写入的 token 数。
        cacheReadInputTokens: Prompt Caching 命中读取的 token 数。
    """

    promptTokens: int = 0
    completionTokens: int = 0
    totalTokens: int = 0
    cacheCreationInputTokens: int = 0
    cacheReadInputTokens: int = 0

    @property
    def cacheHit(self) -> bool:
        """本次调用是否命中 Prompt Caching。"""
        return self.cacheReadInputTokens > 0

    @property
    def cacheCreated(self) -> bool:
        """本次调用是否创建了新的 Prompt Cache。"""
        return self.cacheCreationInputTokens > 0

    @property
    def cacheHitRate(self) -> float:
        """缓存命中率（0-100），cacheReadInputTokens / promptTokens * 100。"""
        if self.promptTokens <= 0:
            return 0.0
        return self.cacheReadInputTokens / self.promptTokens * 100.0

    def __add__(self, other: TokenUsage) -> TokenUsage:
        return TokenUsage(
            promptTokens=self.promptTokens + other.promptTokens,
            completionTokens=self.completionTokens + other.completionTokens,
            totalTokens=self.totalTokens + other.totalTokens,
            cacheCreationInputTokens=self.cacheCreationInputTokens + other.cacheCreationInputTokens,
            cacheReadInputTokens=self.cacheReadInputTokens + other.cacheReadInputTokens,
        )


# ==================== 完整响应 ====================

@dataclass(slots=True)
class ChatResponse:
    """一次非流式调用的完整返回。

    Attributes:
        content: 模型生成的最终文本。
        reasoningContent: DeepSeek-R1 / o1 等推理模型的思考链。
        model: 实际使用的模型名。
        usage: Token 用量。
        finishReason: 停止原因（stop / length / tool_calls 等）。
        rawResponse: 原始响应体（调试用）。
    """

    content: str
    reasoningContent: str = ""
    model: str = ""
    usage: Optional[TokenUsage] = None
    finishReason: str = ""
    rawResponse: Optional[dict] = None
    toolCalls: Optional[list[ToolCall]] = None


# ==================== 流式块 ====================

@dataclass(slots=True)
class ChatChunk:
    """流式调用的单次增量产出。

    Attributes:
        content: 增量文本（最终回答）。
        reasoningContent: 增量思考链（DeepSeek-R1 / o1）。
        usage: 流结束时的汇总用量（仅最后一个块有值）。
        finishReason: 流结束时的停止原因。
        index: 候选序号（多候选场景）。
    """

    content: str = ""
    reasoningContent: str = ""
    usage: Optional[TokenUsage] = None
    finishReason: str = ""
    index: int = 0
    toolCalls: Optional[list[ToolCall]] = None

    @property
    def isEmpty(self) -> bool:
        return (
            not self.content
            and not self.reasoningContent
            and self.usage is None
            and not self.finishReason
            and not self.toolCalls
        )
