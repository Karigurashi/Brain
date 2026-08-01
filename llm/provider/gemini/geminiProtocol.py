"""Google Gemini 协议层，封装消息格式、工具调用、参数构建。"""

from __future__ import annotations

from typing import Any, Optional

from common.const import ERole

from ..chatMessage import ChatMessage, ToolCall, ToolSpec
from ...llmRequestParams import LLMRequestParams


class GeminiProtocol:
    """Google Gemini API 协议封装。

    负责 ChatMessage → Gemini Content/Part 转换、
    ToolSpec → Gemini tools 声明、response → ToolCall 解析。
    """

    # ---- 消息格式 ----

    @staticmethod
    def FormatMessages(messages: list[ChatMessage]) -> list[dict]:
        """将 ChatMessage 列表转为 Gemini contents 格式。

        Gemini 格式: [{"role": "user", "parts": [{"text": "..."}]}]
        system 消息通过 system_instruction 单独处理。
        """
        result: list[dict] = []
        for m in messages:
            if m.role == ERole.SYSTEM:
                continue  # system 在 BuildRequestParams 中处理
            parts: list[dict] = [{"text": m.content}]
            if m.toolCalls:
                for tc in m.toolCalls:
                    parts.append({
                        "functionCall": {
                            "name": tc.name,
                            "args": tc.arguments,
                        },
                    })
            result.append({"role": m.role, "parts": parts})
        return result

    @staticmethod
    def GetSystemInstruction(messages: list[ChatMessage]) -> str | None:
        """提取 system 消息作为 system_instruction。"""
        systemTexts = [m.content for m in messages if m.role == ERole.SYSTEM]
        return "\n".join(systemTexts) if systemTexts else None

    # ---- 工具格式 ----

    @staticmethod
    def FormatTools(tools: list[ToolSpec]) -> list[dict]:
        """将 ToolSpec 列表转为 Gemini functionDeclarations。"""
        result: list[dict] = []
        for t in tools:
            result.append({
                "name": t.name,
                "description": t.description,
                "parameters": t.parameters,
            })
        return result

    # ---- 工具调用解析 ----

    @staticmethod
    def ParseToolCalls(candidates: list[Any]) -> Optional[list[ToolCall]]:
        """从 Gemini response candidates 中提取 function calls。无工具调用时返回 None。"""
        result: Optional[list[ToolCall]] = None
        for candidate in candidates:
            content = getattr(candidate, "content", None)
            if content is None:
                continue
            parts = getattr(content, "parts", [])
            for part in parts:
                fc = getattr(part, "function_call", None)
                if fc is not None:
                    if result is None:
                        result = []
                    result.append(ToolCall(
                        id=getattr(fc, "id", ""),
                        name=getattr(fc, "name", ""),
                        arguments=dict(getattr(fc, "args", {}) or {}),
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
        """聚合构建 Gemini generate_content 请求参数。

        enableThinking / thinkingBudget / enableCache 当前为 Gemini
        预留参数，协议层直接忽略。
        """
        temperature = requestParams.temperature
        maxTokens = requestParams.maxTokens
        extraParams = requestParams.extraParams

        contents = self.FormatMessages(messages)
        systemInstruction = self.GetSystemInstruction(messages)

        params: dict = {
            "model": modelName,
            "contents": contents,
            "config": {},
        }
        if temperature >= 0:
            params["config"]["temperature"] = temperature
        if maxTokens > 0:
            params["config"]["max_output_tokens"] = maxTokens
        if tools:
            params["config"]["tools"] = [{
                "function_declarations": self.FormatTools(tools),
            }]
        if systemInstruction:
            params["config"]["system_instruction"] = systemInstruction
        if extraParams:
            params.update(extraParams)
        return params
