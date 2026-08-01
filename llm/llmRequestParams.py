"""LLM 请求参数数据对象，封装 Provider 级别的额外调用参数。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any, Callable, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from .provider.chatMessage import ChatMessage, ChatResponse, ToolSpec


class EThinkingEffort(str, Enum):
    """Extended Thinking 的思考力度级别。

    使用 str 基类而非 IntEnum：此枚举直接作为 Anthropic API 的
    thinking_effort 字段值透传，无需中间映射。

    Attributes:
        LOW: 最低思考力度，适合简单问答。
        MEDIUM: 中等思考力度，平衡质量与延迟。
        HIGH: 最高思考力度，适合复杂推理任务。
    """

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass
class LLMRequestParams:
    """LLM 调用请求参数

    Attributes:
        temperature: 采样温度，范围 [0, 2]，默认 0.5。
        maxTokens: 最大生成 token 数，0 表示不限制。
        enableThinking: 启用 Extended Thinking（Anthropic Claude）。
        thinkingBudget: Extended Thinking 预算 token 数。
        thinkingEffort: Extended Thinking 思考力度，None 时回退到 budget 模式。

        extraParams: 透传到 API 的额外参数（top_p、frequency_penalty 等）。
        tools: 请求级工具列表，None 表示不携带工具。
        onBeforeRequest: 请求前回调，传入归一化后的消息列表。
        onAfterRequest: 请求后回调，传入完整响应。
        onError: 请求异常回调，传入异常对象。
    """

    temperature: float = 0.5
    maxTokens: int = 0
    enableThinking: bool = False
    thinkingBudget: int = 0
    thinkingEffort: EThinkingEffort = EThinkingEffort.MEDIUM
    extraParams: Optional[dict[str, Any]] = None

    # ——— 请求级回调 ———
    onBeforeRequest: Optional[Callable[[list[ChatMessage]], None]] = None
    onAfterRequest: Optional[Callable[[ChatResponse], None]] = None
    onError: Optional[Callable[[Exception], None]] = None

    # ——— 请求级工具 ———
    tools: Optional[list[ToolSpec]] = None


# 静态默认实例，外部只读使用，避免重复分配
LLMRequestParams.DEFAULT = LLMRequestParams()
