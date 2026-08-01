"""CardComponent —— AgentStreamEvent → 飞书卡片 reply dispatcher 桥接。

保留 mango 流式事件模型；按群串行消费事件，避免与官方 chat-queue
等价路径上的乱序/重复建卡。

取消由 AgentSdk 内部 token 管理；卡片中止走 AbortActive / abortCard，
本组件不再透传 CancellationToken。
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING, Dict, Optional

from app.channel.channelComponent import BaseChannelComponent
from app.feishu.card.replyDispatcher import CreateFeishuReplyDispatcher
from app.feishu.card.replyDispatcherTypes import (
    CreateFeishuReplyDispatcherParams,
    FeishuReplyDispatcherResult,
    FooterSessionMetrics,
)
from app.feishu.card.streamingCardController import DrainShutdownHooksAsync
from app.feishu.card.toolUseConfig import ResolveToolUseDisplayConfig
from app.feishu.card.toolUseTraceStore import (
    ClearToolUseTraceRun,
    RecordToolUseEnd,
    RecordToolUseStart,
    StartToolUseTraceRun,
)
from app.feishu.core.larkClient import LarkClient
from app.feishu.core.types import ReplyPayload
from common.logger import Logger

if TYPE_CHECKING:
    from agent import AgentStreamEvent


@dataclass
class _ReplySession:
    chatId: str
    replyToMessageId: str = ""
    chatType: str = "group"
    result: Optional[FeishuReplyDispatcherResult] = None
    textBuffer: str = ""
    thinkingBuffer: str = ""
    started: bool = False
    textCompleted: bool = False
    generation: int = 0
    # 绑定本轮 Agent runId；None 表示尚未接受 START
    boundRunId: Optional[int] = None


class CardComponent(BaseChannelComponent):
    """飞书卡片组件 —— 每群一组 reply dispatcher，对接 AgentSdk 事件。"""

    def __init__(self) -> None:
        super().__init__()
        self._sessions: Dict[str, _ReplySession] = {}
        self._client: Optional[LarkClient] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._groupLocks: Dict[str, asyncio.Lock] = {}
        self._seenMessageIds: Dict[str, float] = {}
        self._seenMessageIdOrder: list[str] = []

    def OnInitialize(self, entity) -> None:
        super().OnInitialize(entity)
        # 真正的运行循环在 Lifecycle.Start / asyncio.run 之后才存在，
        # 此处不抢绑；由 BindEventLoop / _Schedule 首次捕获。

    def BindEventLoop(self, loop: asyncio.AbstractEventLoop) -> None:
        """绑定 Channel 主事件循环，供 Agent 后台推送跨线程调度。"""
        self._loop = loop

    @property
    def Client(self) -> LarkClient:
        if self._client is None:
            config = self._channel.Config  # type: ignore[union-attr]
            self._client = LarkClient.FromCredentials(config.ToCredentials())
        return self._client

    def IsDuplicateMessage(self, messageId: str) -> bool:
        """轻量入站去重（对齐官方 tryRecord）。"""
        if not messageId:
            return False
        if messageId in self._seenMessageIds:
            return True
        import time

        now = time.time()
        self._seenMessageIds[messageId] = now
        self._seenMessageIdOrder.append(messageId)
        while len(self._seenMessageIdOrder) > 2000:
            old = self._seenMessageIdOrder.pop(0)
            self._seenMessageIds.pop(old, None)
        return False

    async def BeginReplyAsync(
        self,
        chatId: str,
        replyToMessageId: str,
        chatType: str = "group",
    ) -> None:
        """入站消息到达：等待旧卡 abort 完成后再建会话（防交叉）。"""
        async with self._GetLock(chatId):
            existing = self._sessions.get(chatId)
            if existing and existing.result is not None:
                try:
                    await existing.result.abortCard()
                except Exception as err:
                    Logger.Warning(f"BeginReply abort previous failed: {err}")
            generation = (existing.generation + 1) if existing else 1
            self._sessions[chatId] = _ReplySession(
                chatId=chatId,
                replyToMessageId=replyToMessageId,
                chatType=chatType if chatType in ("p2p", "group") else "group",
                generation=generation,
                boundRunId=None,
            )

    def BeginReply(self, chatId: str, replyToMessageId: str, chatType: str = "group") -> None:
        """同步入口：调度 BeginReplyAsync（兼容旧调用）。"""
        self._Schedule(self.BeginReplyAsync(chatId, replyToMessageId, chatType))

    async def AbortActiveAsync(self, chatId: str) -> None:
        """中止当前群的流式卡片（不新建会话）。"""
        async with self._GetLock(chatId):
            existing = self._sessions.get(chatId)
            if existing is None or existing.result is None:
                return
            try:
                await existing.result.abortCard()
            except Exception as err:
                Logger.Warning(f"AbortActive failed: {err}")
            existing.result = None
            existing.started = False
            existing.boundRunId = None
            existing.textBuffer = ""
            existing.thinkingBuffer = ""
            existing.textCompleted = False
            ClearToolUseTraceRun(chatId)

    def OnAgentEventSync(self, groupId: str, event: "AgentStreamEvent") -> None:
        """同步钩子：按群串行调度，不阻塞 EventBus 线程。"""
        self._Schedule(self._RunSerializedAsync(groupId, event))

    async def SendTextResponseAsync(self, groupId: str, content: str) -> None:
        from app.feishu.messaging.outbound.send import SendMessageFeishuAsync

        session = self._sessions.get(groupId)
        replyTo = session.replyToMessageId if session else None
        await SendMessageFeishuAsync(self.Client, groupId, content, replyTo)

    async def CloseAsync(self) -> None:
        await DrainShutdownHooksAsync()
        for session in list(self._sessions.values()):
            if session.result is not None:
                try:
                    await session.result.abortCard()
                except Exception:
                    pass
        self._sessions.clear()
        if self._client is not None:
            await self._client.CloseAsync()
            self._client = None

    # ---- 内部 ----

    def _GetLock(self, groupId: str) -> asyncio.Lock:
        lock = self._groupLocks.get(groupId)
        if lock is None:
            lock = asyncio.Lock()
            self._groupLocks[groupId] = lock
        return lock

    def _Schedule(self, coro) -> None:
        """将协程投递到 Channel 主循环；支持 Agent / EventBus 跨线程推送。"""
        try:
            running = asyncio.get_running_loop()
            self._loop = running
            task = running.create_task(coro)

            def _Done(t: asyncio.Task) -> None:
                try:
                    exc = t.exception()
                except asyncio.CancelledError:
                    return
                if exc is not None:
                    Logger.Error(f"CardComponent task failed: {exc}")

            task.add_done_callback(_Done)
            return
        except RuntimeError:
            pass

        loop = self._loop
        if loop is None or loop.is_closed():
            Logger.Warning("CardComponent: no event loop, drop card update")
            return

        future = asyncio.run_coroutine_threadsafe(coro, loop)

        def _DoneFuture(f) -> None:
            try:
                exc = f.exception()
            except Exception:
                return
            if exc is not None:
                Logger.Error(f"CardComponent task failed: {exc}")

        future.add_done_callback(_DoneFuture)

    async def _RunSerializedAsync(self, groupId: str, event: "AgentStreamEvent") -> None:
        async with self._GetLock(groupId):
            await self._HandleEventAsync(groupId, event)

    async def _EnsureStartedAsync(self, groupId: str, session: _ReplySession, runId: int) -> None:
        """本轮 START：绑定 runId 并建 dispatcher。内容事件不走补建（防陈旧事件拉空卡）。"""
        if session.started and session.boundRunId == runId:
            return
        # 同 session 上新 runId：重置 buffer / dispatcher
        if session.started and session.result is not None and session.boundRunId != runId:
            try:
                await session.result.abortCard()
            except Exception:
                pass
            session.result = None
        session.boundRunId = runId
        session.textBuffer = ""
        session.thinkingBuffer = ""
        session.textCompleted = False
        StartToolUseTraceRun(groupId)
        await self._EnsureDispatcherAsync(session)
        if session.result is not None:
            await session.result.dispatcher.onReplyStart()
        session.started = True

    async def _HandleEventAsync(self, groupId: str, event: "AgentStreamEvent") -> None:
        from agent import EAgentStreamEventType

        session = self._EnsureSession(groupId)
        et = event.eventType
        runId = int(event.runId or 0)

        if et == EAgentStreamEventType.START:
            if runId <= 0:
                return
            await self._EnsureStartedAsync(groupId, session, runId)
            return

        # 必须已 START 且 runId 匹配，否则视为陈旧 Run 尾巴
        if (
            not session.started
            or session.result is None
            or session.boundRunId is None
            or runId != session.boundRunId
        ):
            return

        if et == EAgentStreamEventType.THINKING_DELTA:
            # Agent 发的是 chunk；官方 onReasoningStream / cardElement.content 要累计全文
            # 见 openclaw-lark cardkit.ts: "full cumulative text (not a delta)"
            session.thinkingBuffer += event.content or ""
            if session.result is not None and session.thinkingBuffer:
                await self._CallPartialOrReasoningAsync(
                    session,
                    ReplyPayload(text=session.thinkingBuffer, isReasoning=True),
                )
            return

        if et == EAgentStreamEventType.THINKING_COMPLETE:
            # 权威整段；仅非流式（无 delta）或与累计不一致时补一帧 onReasoningStream
            prev = session.thinkingBuffer
            full = event.content or prev
            session.thinkingBuffer = full
            if session.result is not None and full and (not prev or full != prev):
                await self._CallPartialOrReasoningAsync(
                    session,
                    ReplyPayload(text=full, isReasoning=True),
                )
            return

        if et == EAgentStreamEventType.TEXT_DELTA:
            # Agent 发 chunk；官方 onPartialReply 要累计全文（长度缩短才视为新回复边界）
            session.textBuffer += event.content or ""
            if session.result is not None and session.textBuffer:
                await self._PushAnswerPartialAsync(session, session.textBuffer)
            return

        if et == EAgentStreamEventType.TEXT_COMPLETE:
            # 对齐官方：deliver(final) → onDeliver 写入 completedText 供 onIdle 终态卡
            # 若已有 lastPartialText，onDeliver 不再刷流式 UI（见 streaming-card-controller.ts）
            session.textBuffer = event.content or session.textBuffer
            session.textCompleted = True
            if session.result is not None and session.textBuffer.strip():
                await session.result.dispatcher.deliver(
                    ReplyPayload(text=session.textBuffer),
                    {"kind": "final"},
                )
            # 标记：下一轮内容到达时清空正文重新绘制，避免旧轮次正文残留
            if session.result is not None:
                markReset = session.result.replyOptions.get("markPendingBodyReset")
                if callable(markReset):
                    markReset()
            return

        if et == EAgentStreamEventType.TOOL_START:
            # 每轮工具前清空正文/思考 buffer，防止下一轮 delta 继续 += 造成段落重复
            await self._BeginToolRoundAsync(session)
            if not self._IsBoundRun(session, runId):
                return
            RecordToolUseStart(
                groupId,
                event.toolName or "tool",
                event.toolArgs or {},
                toolCallId=event.toolCallId or None,
            )
            if session.result is not None:
                onToolStart = session.result.replyOptions.get("onToolStart")
                if callable(onToolStart):
                    await onToolStart({"name": event.toolName or "tool", "phase": "start"})
            return

        if et == EAgentStreamEventType.TOOL_RESULT:
            errorText = None
            if event.toolResult is not None and not event.toolResult.success:
                errorText = event.toolResult.error or event.content or "tool failed"
            RecordToolUseEnd(
                groupId,
                event.toolName or "tool",
                result=event.content or "",
                error=errorText,
                toolCallId=event.toolCallId or None,
            )
            # 只刷新工具面板状态；结果正文不 deliver，避免落入卡片正文
            if session.result is not None:
                onToolPayload = session.result.replyOptions.get("onToolPayload")
                if callable(onToolPayload):
                    await onToolPayload(ReplyPayload(text=event.toolName or "tool"))
            return

        if et == EAgentStreamEventType.ERROR:
            if not self._IsBoundRun(session, runId):
                return
            errText = event.error or "unknown error"
            # Cancel 走 abort 终态，避免误显示 Error 模板
            if session.result is not None and _IsCancellationError(errText):
                try:
                    await session.result.abortCard()
                except Exception as abortErr:
                    Logger.Warning(f"cancel abortCard failed: {abortErr}")
            elif session.result is not None:
                await session.result.dispatcher.onError(errText, {"kind": "agent"})
            ClearToolUseTraceRun(groupId)
            session.textBuffer = ""
            session.thinkingBuffer = ""
            session.result = None
            session.started = False
            session.boundRunId = None
            session.textCompleted = False
            return

        if et == EAgentStreamEventType.DONE:
            if not self._IsBoundRun(session, runId):
                return
            if session.result is not None:
                # 无 TEXT_COMPLETE（异常收口）时补 deliver(final)，与官方 final 路径一致
                if not session.textCompleted and session.textBuffer.strip():
                    await session.result.dispatcher.deliver(
                        ReplyPayload(text=session.textBuffer),
                        {"kind": "final"},
                    )
                session.result.markFullyComplete()
                await session.result.dispatcher.onIdle()
                session.result.markDispatchIdle()
            ClearToolUseTraceRun(groupId)
            session.textBuffer = ""
            session.thinkingBuffer = ""
            session.result = None
            session.started = False
            session.boundRunId = None
            session.textCompleted = False
            return

    def _EnsureSession(self, groupId: str) -> _ReplySession:
        session = self._sessions.get(groupId)
        if session is None:
            session = _ReplySession(chatId=groupId)
            self._sessions[groupId] = session
        return session

    async def _EnsureDispatcherAsync(self, session: _ReplySession) -> None:
        if session.result is not None:
            return
        channel = self._channel  # type: ignore[assignment]
        config = channel.Config
        feishuCfg = config.ToCardConfig()
        toolUseDisplay = ResolveToolUseDisplayConfig(feishuCfg, session.chatId)

        async def _GetFooterMetrics() -> FooterSessionMetrics | None:
            try:
                from app.channel import GroupComponent

                groupComponent = channel.GetComponent(GroupComponent)
                promptTokens, completionTokens, cacheHitRate = groupComponent.GetLastTokenUsage(
                    session.chatId
                )
                if promptTokens == 0 and completionTokens == 0:
                    return None
                return FooterSessionMetrics(
                    inputTokens=promptTokens,
                    outputTokens=completionTokens,
                    cacheHitRate=cacheHitRate,
                    totalTokens=promptTokens + completionTokens,
                    totalTokensFresh=True,
                    model=groupComponent.GetModelName(session.chatId),
                )
            except Exception as exc:
                Logger.Debug(f"footer metrics unavailable: {exc}")
                return None

        session.result = CreateFeishuReplyDispatcher(
            CreateFeishuReplyDispatcherParams(
                credentials=self.Client,
                feishuCfg=feishuCfg,
                agentId="mango",
                sessionKey=session.chatId,
                chatId=session.chatId,
                replyToMessageId=session.replyToMessageId or None,
                accountId="default",
                chatType=session.chatType,
                toolUseDisplay=toolUseDisplay,
                getFooterMetrics=_GetFooterMetrics,
            )
        )

    def _IsBoundRun(self, session: _ReplySession, runId: int) -> bool:
        return (
            session.started
            and session.result is not None
            and session.boundRunId is not None
            and runId == session.boundRunId
        )

    async def _BeginToolRoundAsync(self, session: _ReplySession) -> None:
        """工具轮次边界：提交已流式正文，并清空本轮 buffer（Commit 单点）。"""
        if session.result is not None:
            commit = session.result.replyOptions.get("onCommitAnswerSegment")
            if callable(commit):
                result = commit()
                if asyncio.iscoroutine(result):
                    await result
        session.textBuffer = ""
        session.thinkingBuffer = ""
        session.textCompleted = False

    async def _PushAnswerPartialAsync(self, session: _ReplySession, text: str) -> None:
        """推送累计答案文本（流式刷新），不走 OnDeliver 终态叠写。"""
        if session.result is None or not text:
            return
        onPartial = session.result.replyOptions.get("onPartialReply")
        if callable(onPartial):
            await onPartial(ReplyPayload(text=text))
            return
        await session.result.dispatcher.deliver(ReplyPayload(text=text), {"kind": "partial"})

    async def _CallPartialOrReasoningAsync(
        self,
        session: _ReplySession,
        payload: ReplyPayload,
    ) -> None:
        if session.result is None:
            return
        opts = session.result.replyOptions
        if payload.isReasoning:
            onReasoning = opts.get("onReasoningStream")
            if callable(onReasoning):
                await onReasoning(payload)
                return
        await self._PushAnswerPartialAsync(session, payload.text or "")


def _IsCancellationError(error: str) -> bool:
    lowered = (error or "").strip().lower()
    return "cancelled" in lowered or "canceled" in lowered
