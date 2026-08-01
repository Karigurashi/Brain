"""SimpleAgent —— 纯对话 Agent，无 harness，不 ReAct 循环。

继承 BaseAgent，跳过所有 harness 功能（rules、skills、MCP、context compaction），
仅保留 BaseLLM 四维调用接口。事件通过 EventBusComponent 推送。

纯对话逻辑（消息构建、LLM 调用、runLock 保护、异常边界）全部下沉至
SimpleComponent，SimpleAgent 仅负责组件组装和委托。
"""

from __future__ import annotations

from typing import Optional

from common.cancellationToken import CancellationToken
from llm.baseLLM import BaseLLM

from .component.data.dataComponent import DataComponent
from .component.strategy.simpleComponent import SimpleComponent
from .core.baseAgent import BaseAgent


class SimpleAgent(BaseAgent):
    """纯对话 Agent，无任何 harness 功能。

    继承 BaseAgent 四维调用接口，但跳过 LOD0 装填、
    ReAct 循环、工具调度和上下文压缩。适用于纯 LLM 对话场景。
    事件通过 EventBusComponent 推送，调用方订阅 EventBusComponent.Subscribe 即可接收。

    Usage::

        from llm import LLMManager
        from agent import SimpleAgent
        from agent.component.eventBus.agentStreamEvent import EAgentStreamEventType

        llm = LLMManager.GetProvider("gpt-4")
        agent = SimpleAgent(llm)

        async def onEvent(event):
            if event.eventType == EAgentStreamEventType.TEXT_DELTA:
                print(event.content, end="", flush=True)

        agent.GetComponent(EventBusComponent).Subscribe(onEvent)
        await agent.RunAsync("Hello", stream=True)
    """

    def __init__(self, llm: BaseLLM) -> None:
        super().__init__()

        self._dataComp = self.AddComponent(DataComponent)
        self._dataComp.llm = llm
        self._simpleComp = self.GetComponent(SimpleComponent)

    def SetSystemPrompt(self, systemPrompt: str) -> None:
        """设置 System prompt（委托 SimpleComponent）。"""
        self._simpleComp.SetSystemPrompt(systemPrompt)

    # ---- 单轮纯对话 ----

    async def RunAsync(
        self,
        userMessage: str,
        cancellationToken: Optional[CancellationToken] = None,
        stream: Optional[bool] = None,
    ) -> None:
        """单轮纯对话，事件通过 EventBusComponent 推送。

        全部逻辑委托给 SimpleComponent。

        Args:
            userMessage: 用户消息。
            cancellationToken: 取消令牌（可选）。
            stream: True 流式 / False 非流式 / None 使用 AgentConfig.stream。
        """
        await self._simpleComp.RunAsync(
            userMessage, cancellationToken=cancellationToken, stream=stream,
        )

