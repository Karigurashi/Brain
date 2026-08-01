"""Agent 编排器 —— ReAct Agent 组装入口。

继承 BaseAgent，将 BaseLLM + SessionComponent + ContextComponent +
ReActComponent + registries 组装为完整的 ReAct Agent。

ReAct 循环全部逻辑（harness 构建、轮次控制、单轮 Think→Act→Observe、
终止判定、锁保护、异常边界、上下文清理）下沉至 ReActComponent，
Agent 仅负责组件组装和委托。
"""

from __future__ import annotations

from typing import Optional

from common.cancellationToken import CancellationToken

from agent.component.data.agentConfig import AgentConfig
from agent.component.data.dataComponent import DataComponent

from .core.baseAgent import BaseAgent
from .component.strategy.reactComponent import ReActComponent

from llm.baseLLM import BaseLLM


class Agent(BaseAgent):
    """ReAct Agent 组装入口。

    继承 BaseAgent，将 BaseLLM / SessionComponent / ContextComponent /
    ReActComponent 组装为完整的 ReAct Agent。

    ReAct 循环全部逻辑由 ReActComponent 封装，
    Agent 仅负责组件组装和生命周期保护（锁 + 异常边界 + 上下文清理）。
    """

    def __init__(
        self,
        llm: BaseLLM,
        config: AgentConfig | None = None,
    ) -> None:
        super().__init__()

        # ---- 挂载 DataComponent（需预注入 LLM，其余组件即用即取）----
        self._dataComp = self.AddComponent(DataComponent)
        self._dataComp.llm = llm

        if config is not None:
            self._dataComp.config = config

        self._reactComp = self.GetComponent(ReActComponent)

    @property
    def agentId(self) -> int:
        return self._dataComp.agentId

    @property
    def modelName(self) -> str:
        return self._dataComp.llm.modelName

    async def RunAsync(
        self,
        userMessage: str,
        cancellationToken: Optional[CancellationToken] = None,
        stream: Optional[bool] = None,
    ) -> None:
        """异步 ReAct 循环。事件通过 EventBusComponent 推送。

        Args:
            userMessage: 用户消息。
            cancellationToken: 可选取消令牌。
            stream: True 流式 / False 非流式 / None 使用 AgentConfig.stream。
        """
        await self._reactComp.RunAsync(userMessage, cancellationToken, stream=stream)
