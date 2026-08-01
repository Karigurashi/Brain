"""SimpleComponent —— 纯对话组件，封装单轮 LLM 调用编排逻辑。

将 SimpleAgent 中的纯对话逻辑（消息构建、LLM 调用、错误处理）
封装为独立组件。Agent 仅负责组件组装和委托。

流式事件推送与缓冲区管理已下沉至 LLMComponent.StreamAsync，
SimpleComponent 仅负责状态编排（runLock 保护 → THINKING → FINISHED / ERROR）。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from common.cancellationToken import CancellationToken
from llm.provider.chatMessage import ChatMessage

from .strategyComponentBase import StrategyComponentBase

if TYPE_CHECKING:
    from agent.core.baseAgent import BaseAgent


class SimpleComponent(StrategyComponentBase):
    """纯对话组件 —— 封装单轮 LLM 调用编排逻辑。

    挂载到 BaseAgent 后，通过 RunAsync 执行单轮纯对话：
    1. 构建消息列表（可选 System prompt + User message）
    2. runLock 互斥保护
    3. 单轮 LLM 调用（流式/非流式）
    4. 异常边界：CancelledError / Exception → EmitError → raise
    5. finally：EmitDone 保证事件闭合

    用法::

        simpleComp = agent.GetComponent(SimpleComponent)
        simpleComp.SetSystemPrompt("You are helpful.")
        await simpleComp.RunAsync("Hello", stream=True)
    """

    # ---- 生命周期 ----

    def OnInitialize(self, agent: BaseAgent) -> None:
        """挂载后注入依赖组件。"""
        super().OnInitialize(agent)
        self._systemPrompt: str = ""

    def SetSystemPrompt(self, systemPrompt: str) -> None:
        """设置 System prompt（RunAsync 调用前配置）。"""
        self._systemPrompt = systemPrompt

    # ---- 子类钩子 ----

    async def OnRunAsync(
        self,
        userMessage: str,
        cancellationToken: Optional[CancellationToken],
        stream: bool,
    ) -> None:
        """构建消息并执行 LLM 调用。"""
        messages = self._BuildMessages(userMessage, self._systemPrompt)
        if stream:
            await self._llmComp.StreamAsync(
                messages, cancellationToken=cancellationToken,
            )
        else:
            await self._llmComp.InvokeAsync(
                messages, cancellationToken=cancellationToken,
            )

    # ---- 内部 ----

    def _BuildMessages(
        self,
        userMessage: str,
        systemPrompt: str,
    ) -> list[ChatMessage]:
        """构建消息列表：可选的 System prompt + User message。"""
        messages: list[ChatMessage] = []
        if systemPrompt:
            messages.append(ChatMessage.System(systemPrompt))
        messages.append(ChatMessage.User(userMessage))
        return messages
