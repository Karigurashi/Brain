"""ReActComponent —— ReAct 循环组件，封装完整 Think→Act→Observe 编排逻辑。

将 Agent 中的 ReAct 循环骨架（harness 构建、轮次控制、终止判定）、
单轮 LLM 调用（流式/非流式统一）、工具执行编排、
上下文摄入策略、错误处理和取消检查全部封装为独立组件。
Agent 仅负责组件组装和生命周期保护（锁 + 异常边界 + 上下文清理）。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from agent.component.contex.contextComponent import ContextComponent
from agent.component.contex.eContextLodLevel import EContextLodLevel
from agent.component.data.dataComponent import DataComponent
from agent.component.harness.harnessComponent import HarnessComponent
from agent.component.llm.llmComponent import LLMComponent
from agent.component.tool.toolComponent import ToolComponent
from common.cancellationToken import CancellationToken
from common.const import ERole
from common.logger import Logger
from llm.provider.chatMessage import ChatMessage, ToolCall

from .strategyComponentBase import StrategyComponentBase

if TYPE_CHECKING:
    from agent.core.baseAgent import BaseAgent


class ReActComponent(StrategyComponentBase):
    """ReAct 循环组件 —— 封装完整 Think→Act→Observe 编排逻辑。

    挂载到 BaseAgent 后，通过 RunAsync 执行完整 ReAct 循环：
    1. 构建 harness、冷卸载、摄入用户消息
    2. 轮次循环：状态栏注入 → 组装上下文 → 单轮 Think→Act→Observe
    3. 终止判定：正常结束 / maxTurns 超限 / 错误退出

    单轮执行（RunTurnAsync）内聚 LLM 调用、工具执行、上下文摄入、
    错误处理和取消检查，通过 bool 向循环骨架回报结果。

    用法::

        reactComp = agent.GetComponent(ReActComponent)
        await reactComp.RunAsync(userMessage, cancellationToken, stream=True)
    """

    def __init__(self) -> None:
        self._lastContent: str = ""

    # ---- 生命周期 ----

    def OnInitialize(self, agent: BaseAgent) -> None:
        """挂载后注入依赖组件。"""
        super().OnInitialize(agent)
        self._ctxComp: ContextComponent = agent.GetComponent(ContextComponent)
        self._toolComp: ToolComponent = agent.GetComponent(ToolComponent)
        self._dataComp: DataComponent = agent.GetComponent(DataComponent)
        self._harnessComp: HarnessComponent = agent.GetComponent(HarnessComponent)

    # ---- 子类钩子 ----

    async def OnRunAsync(
        self,
        userMessage: str,
        cancellationToken: Optional[CancellationToken],
        stream: bool,
    ) -> None:
        """ReAct 循环核心：harness 构建 → 轮次循环 → 终止判定。"""
        await self._harnessComp.BuildAsync()
        self._ctxComp.AutoColdOffloadIfNeeded()
        self._ctxComp.Ingest(
            ERole.USER, userMessage, lodLevel=EContextLodLevel.SUMMARIZABLE,
        )

        maxTurns = self._dataComp.config.maxTurns
        turn = 0
        while maxTurns == -1 or turn <= maxTurns:
            self._eventBusComp.EmitTurnStart(turn)
            statusBar = self._harnessComp.BuildStatusBar(turn)
            self._ctxComp.Ingest(ERole.USER, statusBar, lodLevel=EContextLodLevel.LATEST_ONLY)
            chatMessages = await self._ctxComp.AssembleAsync()

            outcome = await self.RunTurnAsync(
                turn, chatMessages, cancellationToken, stream,
            )
            if not outcome:
                break
            turn += 1
        else:
            self._HandleMaxTurnsExceeded()

    async def OnFinallyAsync(self) -> None:
        """finally 清理：收尾上下文。"""
        await self._ctxComp.AfterTurnAsync()

    # ---- 终止处理 ----

    def _HandleMaxTurnsExceeded(self) -> None:
        """maxTurns 耗尽，推送 ERROR 并终止。"""
        errorMsg = f"Exceeded max turns ({self._dataComp.config.maxTurns})"
        self._eventBusComp.EmitError(errorMsg)

    # ---- 单轮执行 ----

    async def RunTurnAsync(
        self,
        turn: int,
        chatMessages: list[ChatMessage],
        cancellationToken: Optional[CancellationToken],
        stream: bool,
    ) -> bool:
        """执行单轮 Think→Act→Observe。

        Args:
            turn: 当前 ReAct 轮次序号（从 0 起）。
            chatMessages: 已组装的对话消息列表。
            cancellationToken: 外部取消令牌。
            stream: True 使用流式调用，False 使用非流式调用。

        Returns:
            True — 有工具调用已执行，继续下一轮。
            False — 纯文本响应，结束循环。
        """

        if stream:
            result = await self._llmComp.StreamAsync(
                chatMessages, turnIndex=turn, cancellationToken=cancellationToken,
            )
        else:
            result = await self._llmComp.InvokeAsync(
                chatMessages, turnIndex=turn, cancellationToken=cancellationToken,
            )

        self._lastContent = result.content

        # 纯文本响应：摄入 ASSISTANT 后结束循环
        if not result.toolCalls:
            self._ctxComp.IngestAssistant(
                result.content,
                thinkingContent=self._llmComp.LastThinkingContent,
            )
            return False

        # 有工具调用：执行工具并摄入结果
        await self._ExecuteToolCallsAsync(turn, result.toolCalls)
        return True

    # ---- 工具执行 ----

    async def _ExecuteToolCallsAsync(
        self,
        turn: int,
        toolCalls: list[ToolCall],
    ) -> None:
        """执行工具调用、推送工具事件、摄入工具结果到上下文。"""

        for tc in toolCalls:
            self._eventBusComp.EmitToolStart(tc.name, tc.arguments, turn, tc.id)
        results = await self._toolComp.DispatchBatchAsync(toolCalls)
        if results is None:
            return

        for tc, result in zip(toolCalls, results):
            self._eventBusComp.EmitToolResult(tc.name, result, turn, tc.id)

        # Ingest ASSISTANT（空 content 合法：LLM 可仅返回 toolCalls）
        self._ctxComp.IngestAssistant(
            self._lastContent,
            thinkingContent=self._llmComp.LastThinkingContent,
            toolCalls=toolCalls,
        )

        # Ingest TOOL 结果（含 roleMessage 注入）
        for tc, result in zip(toolCalls, results):
            # 对标 Claude Code Skill 工具的 newMessages：
            # 在 tool_result 之前以 USER 角色注入 roleMessage
            if result.roleMessage:
                self._ctxComp.Ingest(
                    ERole.USER,
                    result.roleMessage,
                    lodLevel=EContextLodLevel.SUMMARIZABLE,
                )

            tool = self._toolComp.Get(tc.name)
            lodLevel = (
                tool.resultLodLevel
                if tool is not None and tool.resultLodLevel is not None
                else EContextLodLevel.DISCARDABLE
            )
            skipPersist = tool.skipPersist if tool is not None else False
            self._ctxComp.IngestTool(
                toolCallId=tc.id,
                content=result.ToLLMContent(),
                lodLevel=lodLevel,
                skipPersist=skipPersist,
            )
