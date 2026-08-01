"""OpenAI 兼容协议层，封装消息格式、工具调用、参数构建。"""

from __future__ import annotations

from typing import Any, Optional

from ..chatMessage import ChatMessage, ToolCall, ToolSpec
from ...llmRequestParams import LLMRequestParams


class OpenAIProtocol:
    """OpenAI /chat/completions 协议封装。

    负责 ChatMessage → OpenAI dict 转换、ToolSpec → tools 数组、
    OpenAI response → ToolCall 解析。
    """

    # ---- 消息格式 ----

    @staticmethod
    def FormatMessages(messages: list[ChatMessage]) -> list[dict]:
        """将 ChatMessage 列表转为 OpenAI messages 格式。"""
        return [m.ToOpenAI() for m in messages]

    # ---- 工具格式 ----

    @staticmethod
    def FormatTools(tools: list[ToolSpec]) -> list[dict]:
        """将 ToolSpec 列表转为 OpenAI tools 数组。"""
        result: list[dict] = []
        for t in tools:
            result.append({
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.parameters,
                },
            })
        return result

    # ---- 工具调用解析 ----

    @staticmethod
    def ParseToolCalls(choice: Any) -> Optional[list[ToolCall]]:
        """从 OpenAI response choice 中提取 tool_calls。无工具调用时返回 None。"""
        rawCalls = getattr(getattr(choice, "message", None), "tool_calls", None)
        if not rawCalls:
            return None
        result: list[ToolCall] = []
        for tc in rawCalls:
            func = getattr(tc, "function", None)
            name = getattr(func, "name", "") if func else ""
            argsRaw = getattr(func, "arguments", "{}") if func else "{}"
            try:
                import json
                args = json.loads(argsRaw) if isinstance(argsRaw, str) else argsRaw
            except (json.JSONDecodeError, TypeError):
                args = {}
            result.append(ToolCall(
                id=getattr(tc, "id", ""),
                name=name,
                arguments=args if isinstance(args, dict) else {},
            ))
        return result

    # ---- 参数构建 ----

    def BuildRequestParams(
        self,
        messages: list[ChatMessage],
        requestParams: LLMRequestParams,
        stream: bool,
        tools: list[ToolSpec] | None = None,
        modelName: str = "",
    ) -> dict:
        """聚合构建 OpenAI /chat/completions 请求参数。"""
        temperature = requestParams.temperature
        maxTokens = requestParams.maxTokens
        extraParams = requestParams.extraParams

        params: dict = {
            "model": modelName,
            "messages": self.FormatMessages(messages),
            "temperature": temperature,
            "stream": stream,
        }
        if maxTokens > 0:
            params["max_tokens"] = maxTokens
        if stream:
            params["stream_options"] = {"include_usage": True}
        if tools:
            params["tools"] = self.FormatTools(tools)

        if extraParams:
            params.update(extraParams)
        return params
