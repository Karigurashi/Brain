"""Token 估算器 —— 优先使用 tiktoken 精确计数，降级到 chars/4 近似估算。

支持 OpenAI/Anthropic 主流模型的编码自动选择。
纯实例模式：每个 Agent 通过 LLMComponent 持有独立实例，多 Agent 并发互不干扰。
"""

from __future__ import annotations

from typing import Any

# ---- tiktoken 延迟加载（进程级缓存，编码器本身是无状态线程安全的） ----

_tiktokenAvailable: bool = False
_EncodingCache: dict[str, object] = {}


def _TryLoadTiktoken() -> bool:
    global _tiktokenAvailable
    if _tiktokenAvailable:
        return True
    try:
        import tiktoken  # noqa: F811
        _tiktokenAvailable = True
        return True
    except ImportError:
        return False


def _GetEncoding(encodingName: str) -> object | None:
    """获取缓存的 tiktoken 编码实例。"""
    if not _TryLoadTiktoken():
        return None
    if encodingName in _EncodingCache:
        return _EncodingCache[encodingName]
    try:
        import tiktoken
        enc = tiktoken.get_encoding(encodingName)
        _EncodingCache[encodingName] = enc
        return enc
    except Exception:
        return None


def _GetEncodingForModel(modelName: str) -> object | None:
    """根据模型名自动选择编码。"""
    if not _TryLoadTiktoken():
        return None
    try:
        import tiktoken
        enc = tiktoken.encoding_for_model(modelName)
        _EncodingCache[modelName] = enc
        return enc
    except Exception:
        return None


class TokenEstimator:
    """Token 数量估算器。

    Supports instance mode only: each Agent holds an independent TokenEstimator
    via LLMComponent, ensuring multi-Agent isolation.

    Usage::

        estimator = TokenEstimator(modelName="gpt-4o")
        tokens = estimator.Estimate(text)
    """

    # ---- 主流编码常量 ----

    ENCODING_CL100K = "cl100k_base"       # GPT-4, GPT-3.5-turbo, text-embedding-ada-002
    ENCODING_O200K = "o200k_base"          # GPT-4o, GPT-4o-mini
    ENCODING_P50K = "p50k_base"            # GPT-3 (davinci, etc.)
    ENCODING_R50K = "r50k_base"            # GPT-3 (curie, babbage, etc.)

    _DEFAULT_ENCODING = ENCODING_CL100K

    # ---- 实例级配置（每个 Agent 独立隔离） ----

    def __init__(
        self,
        encodingName: str = "",
        modelName: str = "",
        charsPerToken: float = 4.0,
        overheadPerMessage: int = 4,
    ) -> None:
        self._encodingName = encodingName
        self._modelName = modelName
        self._charsPerToken = charsPerToken
        self._overheadPerMessage = overheadPerMessage
        self._encoder: object | None = None

    # ---- 实例级方法（推荐） ----

    def Configure(
        self,
        encodingName: str = "",
        modelName: str = "",
        charsPerToken: float = 4.0,
        overheadPerMessage: int = 4,
    ) -> None:
        """配置编码器参数，调用后自动重置缓存。"""
        self._encodingName = encodingName
        self._modelName = modelName
        self._charsPerToken = charsPerToken
        self._overheadPerMessage = overheadPerMessage
        self._encoder = None

    def Estimate(self, text: str) -> int:
        """估算单段文本的 token 数（优先 tiktoken 精确计数）。"""
        if not text:
            return 0
        encoder = self._GetEncoder()
        if encoder is not None:
            return max(1, len(encoder.encode(text)))
        return max(1, int(len(text) / self._charsPerToken))

    def EstimateMessage(self, msg: Any) -> int:
        """估算单条消息的 token 数（含 role/metadata 开销）。

        msg 需具备 .content 属性（duck-type，兼容 ContextMessage 等）。

        计入所有协议层字段：content、thinkingContent、toolCalls（JSON 序列化）、
        toolCallId、以及固定协议开销。
        """
        tokens = self._overheadPerMessage
        tokens += self.Estimate(msg.content) if msg.content else 0

        thinkingContent = getattr(msg, "thinkingContent", "")
        if thinkingContent:
            tokens += self.Estimate(thinkingContent)

        # Assistant 消息携带的工具调用 JSON 结构（对标 ChatMessage.ToOpenAI 序列化）
        toolCalls = getattr(msg, "toolCalls", None)
        if toolCalls:
            import json
            for tc in toolCalls:
                tcJson = json.dumps({
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.name,
                        "arguments": json.dumps(tc.arguments, ensure_ascii=False),
                    },
                }, ensure_ascii=False)
                tokens += self.Estimate(tcJson)

        # Tool 消息携带的 tool_call_id 字段
        toolCallId = getattr(msg, "toolCallId", "")
        if toolCallId:
            tokens += self.Estimate(toolCallId)

        return tokens

    def EstimateMessages(self, messages: list) -> int:
        """估算消息列表的总 token 数。"""
        return sum(self.EstimateMessage(m) for m in messages)

    def EstimateByLod(self, messages: list) -> dict[str, int]:
        """按 LOD 分组统计 token 占用。

        messages 中的元素需具备 .content 和 .lodLevel 属性。

        Returns:
            {"LOD0": N, "LOD1": N, "LOD2": N, "LOD3": N, "LOD4": N}
        """
        stats: dict[str, int] = {"LOD0": 0, "LOD1": 0, "LOD2": 0, "LOD3": 0, "LOD4": 0}
        for msg in messages:
            key = f"LOD{msg.lodLevel.value}"
            stats[key] = stats.get(key, 0) + self.EstimateMessage(msg)
        return stats

    def IsWithinBudget(self, messages: list, budget: int) -> bool:
        """判断消息列表是否在 token 预算内。"""
        return self.EstimateMessages(messages) <= budget

    def UsesTiktoken(self) -> bool:
        """当前是否使用 tiktoken 精确计数。"""
        return self._GetEncoder() is not None

    def _GetEncoder(self) -> object | None:
        """获取当前可用的编码器，优先按模型名匹配。"""
        if self._encoder is not None:
            return self._encoder

        if self._modelName:
            enc = _GetEncodingForModel(self._modelName)
            if enc is not None:
                self._encoder = enc
                return enc

        encodingName = self._encodingName or self._DEFAULT_ENCODING
        enc = _GetEncoding(encodingName)
        if enc is not None:
            self._encoder = enc
        return enc
