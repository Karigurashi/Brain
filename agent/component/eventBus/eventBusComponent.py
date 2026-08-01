"""EventBusComponent —— Agent 流式事件总线组件，供外部监听器实时订阅。

将 AgentStreamEvent 的构造与 Push 封装为 EmitXxx 便捷方法，
外部调用方无需直接接触 AgentStreamEvent 工厂方法和 Push。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from common.logger import Logger
from common.syncEventBus import SyncEventBus
from .agentStreamEvent import AgentStreamEvent
from agent.core.baseComponent import BaseComponent

if TYPE_CHECKING:
    from agent.core.baseAgent import BaseAgent
    from agent.component.tool.toolResult import ToolResult


class EventBusComponent(SyncEventBus[AgentStreamEvent], BaseComponent):
    """Agent 流式事件总线组件。

    继承 SyncEventBus 泛型基类（绑定 AgentStreamEvent），
    同时继承 BaseComponent 获得组件生命周期。

    提供 EmitXxx 便捷方法封装事件构造与推送，外部无需直接
    构造 AgentStreamEvent 或调用 Push。
    """

    def __init__(self) -> None:
        super().__init__()
        self._currentRunId: int = 0

    def OnInitialize(self, agent: BaseAgent) -> None:
        """挂载后初始化。当前无需注入其他组件。"""
        pass

    def OnDestroy(self) -> None:
        """卸载时清空所有监听器，避免泄漏。"""
        self.RemoveAllListeners()

    def BeginRun(self, runId: int) -> None:
        """标记本轮 Run 序号；后续 Push 的事件自动带上 runId。

        调用方必须保证：上一轮 Run 的 EmitDone 已执行完毕后再调用。
        否则旧 finally 里的 EmitDone/EmitError 会被打上新 runId，污染下游。
        """
        self._currentRunId = runId

    def Push(self, event: AgentStreamEvent) -> None:
        # 每次 Push 时读取当前 runId（非事件构造时捕获）；故 BeginRun 时序必须正确
        event.runId = self._currentRunId
        super().Push(event)

    # ---- 便捷推送方法 ----

    def EmitError(self, error: str, turnIndex: int = 0) -> None:
        """推送错误事件。"""
        Logger.Error(f"[Agent] {error}")
        self.Push(AgentStreamEvent.ErrorEvent(error, turnIndex))

    def EmitTurnStart(self, turnIndex: int) -> None:
        """推送轮次开始事件。"""
        self.Push(AgentStreamEvent.TurnStart(turnIndex))

    def EmitToolStart(
        self,
        toolName: str,
        toolArgs: dict,
        turnIndex: int = 0,
        toolCallId: str = "",
    ) -> None:
        """推送工具调用开始事件。"""
        self.Push(AgentStreamEvent.ToolStart(toolName, toolArgs, turnIndex, toolCallId))

    def EmitToolResult(
        self,
        toolName: str,
        result: ToolResult,
        turnIndex: int = 0,
        toolCallId: str = "",
    ) -> None:
        """推送工具执行结果事件。"""
        self.Push(AgentStreamEvent.ToolResultEvent(toolName, result, turnIndex, toolCallId))

    def EmitStart(self) -> None:
        """推送 RunAsync 入口事件（与 EmitDone 配对，仅触发一次）。"""
        self.Push(AgentStreamEvent.Start())

    def EmitDone(self) -> None:
        """推送本轮结束事件。"""
        self.Push(AgentStreamEvent.Done())

    def EmitCompaction(self, tokenSaved: int = 0, compactedCount: int = 0, turnIndex: int = 0) -> None:
        """推送上下文压缩事件。"""
        self.Push(AgentStreamEvent.Compaction(tokenSaved, compactedCount, turnIndex))

    def EmitTextDelta(self, content: str, turnIndex: int = 0) -> None:
        """推送文本增量事件。"""
        self.Push(AgentStreamEvent.TextDelta(content, turnIndex))

    def EmitTextComplete(self, content: str, turnIndex: int = 0) -> None:
        """推送文本完成事件。"""
        self.Push(AgentStreamEvent.TextComplete(content, turnIndex))

    def EmitThinkingDelta(self, content: str, turnIndex: int = 0) -> None:
        """推送思考增量事件。"""
        self.Push(AgentStreamEvent.ThinkingDelta(content, turnIndex))

    def EmitThinkingComplete(self, content: str, turnIndex: int = 0) -> None:
        """推送思考完成事件。"""
        self.Push(AgentStreamEvent.ThinkingComplete(content, turnIndex))
