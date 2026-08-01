"""上下文引擎：编排 Ingest → Assemble → Compact → AfterTurn 四阶段生命周期。

ContextComponent 不存储消息；消息统一归属 SessionComponent。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from agent.core.baseComponent import BaseComponent
from agent.component.data.agentConfig import AgentConfig
from agent.component.data.dataComponent import DataComponent
from agent.component.eventBus.eventBusComponent import EventBusComponent
from agent.component.llm.llmComponent import LLMComponent
from agent.component.session.sessionComponent import SessionComponent
from agent.component.store.storeComponent import StoreComponent
from common.const import ERole
from llm.provider.chatMessage import ChatMessage, ToolCall

from .contextCompactor import ContextCompactor
from .contextMessage import ContextMessage
from .eContextLodLevel import EContextLodLevel

if TYPE_CHECKING:
    from agent.core.baseAgent import BaseAgent


class ContextComponent(BaseComponent):
    """上下文引擎：SessionComponent 与 LLM 之间的调度器。

    四阶段：Ingest（摄入）→ AssembleAsync（组装）→ CompactAsync（压缩）→ AfterTurnAsync（收尾）
    """

    def __init__(self) -> None:
        self._sessionComponent: SessionComponent | None = None
        self._llmComponent: LLMComponent | None = None
        self._eventBusComponent: EventBusComponent | None = None
        self._storeComp: StoreComponent | None = None
        self._config: AgentConfig | None = None
        self._compactor: ContextCompactor | None = None
        self._chatMessages: list[ChatMessage] = []

    def OnInitialize(self, agent: BaseAgent) -> None:
        dataComp = agent.GetComponent(DataComponent)
        self._config = dataComp.config
        
        self._sessionComponent = agent.GetComponent(SessionComponent)
        self._llmComponent = agent.GetComponent(LLMComponent)
        self._eventBusComponent = agent.GetComponent(EventBusComponent)

        self._storeComp = agent.GetComponent(StoreComponent)
        self._compactor = ContextCompactor(
            self._config,
            self._storeComp,
            llm=self._llmComponent.llm,
            estimateTokens=self._llmComponent.EstimateTokens,
        )

    def OnDestroy(self) -> None:
        pass

    # ---- Ingest ----

    @staticmethod
    def DefaultLodForRole(role: ERole) -> EContextLodLevel:
        if role == ERole.SYSTEM:
            return EContextLodLevel.RESIDENT
        if role == ERole.TOOL:
            return EContextLodLevel.DISCARDABLE
        if role in (ERole.USER, ERole.ASSISTANT):
            return EContextLodLevel.SUMMARIZABLE
            
        return EContextLodLevel.DISCARDABLE

    def PersistToolResult(self, content: str, skipPersist: bool = False) -> str:
        """工具结果落盘+预览。超阈值时落盘或截断。"""
        threshold = self._config.persistCharThreshold
        previewChars = self._config.persistPreviewChars

        if len(content) <= threshold:
            return content

        if not skipPersist and self._config.enablePersist:
            storePath = self._storeComp.Store(content)
            return self._storeComp.BuildPersistedPreview(storePath, content, previewChars)

        return f"[TRUNC {len(content)}→{previewChars}] {content[:previewChars]}... read_file start_line/end_line"

    def Ingest(
        self,
        role: ERole,
        content: str,
        lodLevel: EContextLodLevel | None = None,
        toolCalls: list[ToolCall] | None = None,
        toolCallId: str = "",
        thinkingContent: str = "",
        skipPersist: bool = False,
    ) -> ContextMessage:
        """摄入一条消息到 SessionComponent。lodLevel 不传时按 role 自动判定。"""
        if lodLevel is None:
            lodLevel = self.DefaultLodForRole(role)

        contextMsg = ContextMessage.Create(
            chatMessage=ChatMessage(
                role=role,
                content=content,
                thinkingContent=thinkingContent,
                toolCalls=toolCalls,
                toolCallId=toolCallId,
            ),
            lodLevel=lodLevel,
            skipPersist=skipPersist,
        )
        self._sessionComponent.Append(contextMsg)
        return contextMsg

    def IngestAssistant(
        self,
        content: str,
        thinkingContent: str = "",
        toolCalls: list[ToolCall] | None = None,
    ) -> None:
        """摄入 ASSISTANT 响应。"""
        self.Ingest(
            ERole.ASSISTANT,
            content,
            lodLevel=EContextLodLevel.SUMMARIZABLE,
            toolCalls=toolCalls,
            thinkingContent=thinkingContent,
        )

    def IngestTool(
        self,
        toolCallId: str,
        content: str,
        lodLevel: EContextLodLevel,
        skipPersist: bool = False,
    ) -> None:
        """摄入工具结果（含落盘+截断）。"""
        ingestContent = self.PersistToolResult(content, skipPersist)
        self.Ingest(
            ERole.TOOL,
            ingestContent,
            lodLevel=lodLevel,
            toolCallId=toolCallId,
            skipPersist=skipPersist,
        )

    # ---- Assemble / Compact / AfterTurn ----

    def AutoColdOffloadIfNeeded(self) -> None:
        """每轮对话前检测宽限期并执行冷卸载。"""
        messages = self._sessionComponent.conversationMessages
        if self._compactor.IsWithinGracePeriod(messages):
            return
        self._compactor.OffloadColdLod2InPlace(messages, 0)

    async def AssembleAsync(self) -> list[ChatMessage]:
        """从 Session 组装消息列表。超预算时自动压缩。"""
        residentMessages = self._sessionComponent.residentMessages
        conversationMessages = self._sessionComponent.conversationMessages
        estimated = self._llmComponent.LastPromptTokens

        if estimated >= self._config.effectiveBudget:
            await self.CompactAsync(force=True)

        self._chatMessages.clear()
        for cm in residentMessages:
            self._chatMessages.append(cm.chatMessage)
        for cm in conversationMessages:
            self._chatMessages.append(cm.chatMessage)
        return self._chatMessages

    async def CompactAsync(self, force: bool = False) -> int:
        """容量管理：先冷卸载 LOD2/LOD3，后 LLM 摘要压缩 SUMMARIZABLE。"""
        budget = self._config.effectiveBudget
        threshold = int(budget * self._config.compactThreshold)
        messages = self._sessionComponent.conversationMessages
        beforeTokens = self._llmComponent.EstimateTokens(messages)

        if not force and beforeTokens <= threshold:
            return 0

        result = await self._compactor.ManageCapacityAsync(
            messages=messages,
            tokenBudget=threshold,
            preEstimatedTokens=beforeTokens,
            force=force,
        )

        if result.compactedCount == 0 and not result.newSummaryMessages:
            afterTokens = self._llmComponent.EstimateTokens(result.messages)
            tokenSaved = max(beforeTokens - afterTokens, 0)
            if tokenSaved > 0:
                self._eventBusComponent.EmitCompaction(
                    tokenSaved=tokenSaved, compactedCount=0)
            return tokenSaved

        self._sessionComponent.ApplyCompactionResult(result.messages)
        self._sessionComponent.FixOrphanedToolCalls()

        afterTokens = self._llmComponent.EstimateTokens(result.messages)
        tokenSaved = max(beforeTokens - afterTokens, 0)

        if tokenSaved > 0:
            self._eventBusComponent.EmitCompaction(
                tokenSaved=tokenSaved, compactedCount=result.compactedCount)
        return tokenSaved

    async def AfterTurnAsync(self) -> None:
        """清除所有 LOD4 消息。"""
        self._sessionComponent.ClearLod4()
