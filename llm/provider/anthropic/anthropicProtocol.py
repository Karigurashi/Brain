"""Anthropic Messages API 协议层，封装消息格式、工具调用、KV-Cache、Extended Thinking。"""

from __future__ import annotations

from typing import Any, Optional

from common.const import ERole

from ..chatMessage import ChatMessage, ToolCall, ToolSpec
from ...llmRequestParams import LLMRequestParams


class AnthropicProtocol:
    """Anthropic Messages API 协议封装。

    负责 ChatMessage → Anthropic dict 转换、system 消息分离、
    ToolSpec → tools 数组、response content block → ToolCall 解析、
    Extended Thinking 配置。
    """

    # ---- 消息格式 ----

    @staticmethod
    def FormatMessages(messages: list[ChatMessage]) -> tuple[list[str], list[dict]]:
        """分离 system 消息并转换格式，正确编码工具回合。

        Anthropic 不接受 ``role="tool"``，且工具调用须以 content block 表达：
        - assistant 发起调用 → ``tool_use`` block（与可选 text block 同一条消息）；
        - 工具结果 → 归入紧随其后的 ``user`` 消息的 ``tool_result`` block，
          多个连续工具结果（并行调用）合并到同一条 user 消息。

        Returns:
            (systemPrompts, chatMessages): system 文本列表 + 对话消息列表。
        """
        systemPrompts: list[str] = []
        chatMessages: list[dict] = []
        pendingToolResults: list[dict] = []

        def _FlushToolResults() -> None:
            if pendingToolResults:
                chatMessages.append({"role": "user", "content": list(pendingToolResults)})
                pendingToolResults.clear()

        for m in messages:
            if m.role == ERole.SYSTEM:
                systemPrompts.append(m.content)
                continue

            if m.role == ERole.TOOL:
                pendingToolResults.append({
                    "type": "tool_result",
                    "tool_use_id": m.toolCallId,
                    "content": m.content,
                })
                continue

            # 非工具结果消息：先冲刷待合并的工具结果，保证顺序正确
            _FlushToolResults()

            if m.role == ERole.ASSISTANT and m.toolCalls:
                d = AnthropicProtocol._BuildToolUseMessage(m)
            else:
                d = m.ToAnthropic()

            chatMessages.append(d)

        _FlushToolResults()
        return systemPrompts, chatMessages

    @staticmethod
    def _BuildToolUseMessage(message: ChatMessage) -> dict:
        """将携带 toolCalls 的 assistant 消息转为 Anthropic tool_use content block。"""
        blocks: list[dict] = []
        if message.content:
            blocks.append({"type": "text", "text": message.content})
        for tc in message.toolCalls or []:
            blocks.append({
                "type": "tool_use",
                "id": tc.id,
                "name": tc.name,
                "input": tc.arguments,
            })
        return {"role": "assistant", "content": blocks}

    # ---- 工具格式 ----

    @staticmethod
    def FormatTools(tools: list[ToolSpec]) -> list[dict]:
        """将 ToolSpec 列表转为 Anthropic tools 数组。"""
        result: list[dict] = []
        for t in tools:
            result.append({
                "name": t.name,
                "description": t.description,
                "input_schema": t.parameters,
            })
        return result

    # ---- 工具调用解析 ----

    @staticmethod
    def ParseToolCalls(contentBlocks: list[Any]) -> Optional[list[ToolCall]]:
        """从 Anthropic response content blocks 中提取 tool_use。无工具调用时返回 None。"""
        result: Optional[list[ToolCall]] = None
        for block in contentBlocks:
            if getattr(block, "type", "") == "tool_use":
                if result is None:
                    result = []
                result.append(ToolCall(
                    id=getattr(block, "id", ""),
                    name=getattr(block, "name", ""),
                    arguments=getattr(block, "input", {}) or {},
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
        """聚合构建 Anthropic Messages API 请求参数。"""
        temperature = requestParams.temperature
        maxTokens = requestParams.maxTokens
        enableThinking = requestParams.enableThinking
        thinkingBudget = requestParams.thinkingBudget
        thinkingEffort = requestParams.thinkingEffort
        extraParams = requestParams.extraParams

        systemPrompts, chatMessages = self.FormatMessages(messages)

        params: dict = {
            "model": modelName,
            "messages": chatMessages,
            "max_tokens": maxTokens if maxTokens > 0 else 4096,
            "temperature": temperature,
        }
        if systemPrompts:
            params["system"] = "\n".join(systemPrompts)
        if tools:
            params["tools"] = self.FormatTools(tools)

        # Extended Thinking
        if enableThinking:
            if thinkingBudget > 0:
                params["thinking"] = {"type": "enabled", "budget_tokens": thinkingBudget}
                params["temperature"] = 1
            else:
                params["thinking"] = {"type": "enabled", "thinking_effort": thinkingEffort.value}
                params["temperature"] = 1

        if extraParams:
            params.update(extraParams)
        return params
