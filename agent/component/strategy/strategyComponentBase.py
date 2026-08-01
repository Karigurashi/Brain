"""StrategyComponentBase —— Agent 执行策略基类，封装 runLock 保护 + 统一异常边界 + 事件闭合。

ReActComponent、SimpleComponent 等执行策略组件继承此基类，
RunAsync 提供统一的锁保护和异常处理骨架，
子类通过 _OnRunAsync 实现具体执行逻辑。
"""

from __future__ import annotations

import abc
from typing import TYPE_CHECKING, Optional

from agent.component.data.dataComponent import DataComponent
from agent.component.eventBus.eventBusComponent import EventBusComponent
from agent.component.llm.llmComponent import LLMComponent
from agent.component.loop.loopComponent import LoopComponent
from agent.core.baseComponent import BaseComponent
from common.cancellationToken import CancellationToken, CancelledError

if TYPE_CHECKING:
    from agent.core.baseAgent import BaseAgent


class StrategyComponentBase(BaseComponent):
    """Agent 执行策略基类。

    RunAsync 提供模板骨架：
    1. runLock 互斥锁 —— 保证单 Agent 不并发运行
    2. _OnRunAsync 钩子 —— 子类实现具体执行逻辑
    3. 两级异常捕获 —— CancelledError / Exception → EmitError → raise
    4. finally 事件闭合 —— EmitDone + 可选子类清理钩子 _OnFinallyAsync
    """

    # ---- 生命周期 ----

    def OnInitialize(self, agent: BaseAgent) -> None:
        """挂载后注入公共依赖组件（EventBus / Loop / LLM / Data）。"""
        self._agent: BaseAgent = agent
        self._eventBusComp: EventBusComponent = agent.GetComponent(EventBusComponent)
        self._loopComp: LoopComponent = agent.GetComponent(LoopComponent)
        self._llmComp: LLMComponent = agent.GetComponent(LLMComponent)
        self._dataComp: DataComponent = agent.GetComponent(DataComponent)

    def OnDestroy(self) -> None:
        """卸载时回调。"""
        pass

    # ---- 模板入口：外部直接调用 ----

    async def RunAsync(
        self,
        userMessage: str,
        cancellationToken: Optional[CancellationToken] = None,
        stream: Optional[bool] = None,
    ) -> None:
        """执行模板骨架：runLock 保护 → _OnRunAsync → 异常边界 → finally 闭合。

        Args:
            userMessage: 用户消息。
            cancellationToken: 取消令牌（可选）。
            stream: True 流式 / False 非流式 / None 使用 AgentConfig.stream。
        """
        if stream is None:
            stream = self._dataComp.config.stream
        async with self._loopComp.runLock:
            try:
                self._eventBusComp.EmitStart()
                await self.OnRunAsync(userMessage, cancellationToken, stream)
            except CancelledError:
                self._eventBusComp.EmitError("Cancelled by user")
                raise
            except Exception as exc:
                self._eventBusComp.EmitError(f"LLM call failed: {exc}")
                raise
            finally:
                await self.OnFinallyAsync()
                self._eventBusComp.EmitDone()

    # ---- 子类钩子 ----

    @abc.abstractmethod
    async def OnRunAsync(
        self,
        userMessage: str,
        cancellationToken: Optional[CancellationToken],
        stream: bool,
    ) -> None:
        """子类实现：具体执行逻辑。"""
        ...

    def SetSystemPrompt(self, systemPrompt: str) -> None:
        """设置 System prompt（RunAsync 调用前配置，子类按需覆盖）。"""
        pass

    async def OnFinallyAsync(self) -> None:
        """finally 清理钩子，子类可覆盖以添加额外清理（如 AfterTurnAsync）。"""
        pass
