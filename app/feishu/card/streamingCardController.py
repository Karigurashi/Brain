"""流式卡片生命周期控制器。"""

from __future__ import annotations

import asyncio
import time
from typing import Any, Optional

from app.feishu.card.builder import (
    REASONING_ELEMENT_ID,
    STREAMING_ELEMENT_ID,
    BuildCardContent,
    BuildStreamingPreAnswerCard,
    BuildStreamingThinkingCard,
    SplitReasoningText,
    StripReasoningTags,
    ToCardKit2,
    TruncateReasoningForDisplay,
)
from app.feishu.card.cardError import (
    FEISHU_CARD_TABLE_LIMIT,
    IsCardRateLimitError,
    IsCardTableLimitError,
    SanitizeTextSegmentsForCard,
)
from app.feishu.card.cardkit import (
    CreateCardEntityAsync,
    SendCardByCardIdAsync,
    SetCardStreamingModeAsync,
    StreamCardContentAsync,
    UpdateCardKitCardAsync,
)
from app.feishu.card.flushController import FlushController
from app.feishu.card.imageResolver import ImageResolver
from app.feishu.card.markdownStyle import OptimizeMarkdownStyle
from app.feishu.card.replyDispatcherTypes import (
    CARD_PHASE_NAMES,
    EMPTY_REPLY_FALLBACK_TEXT,
    ECardPhase,
    PHASE_TRANSITIONS,
    TERMINAL_PHASES,
    THROTTLE_CONSTANTS,
    CardKitState,
    FooterSessionMetrics,
    ReasoningState,
    StreamingCardDeps,
    StreamingTextState,
    ToolUseState,
)
from app.feishu.card.toolUseDisplay import BuildToolUseTitleSuffix, NormalizeToolUseDisplay
from app.feishu.card.toolUseTraceStore import ClearToolUseTraceRun, GetToolUseTraceSteps
from app.feishu.card.unavailableGuard import UnavailableGuard
from app.feishu.core.apiError import ExtractLarkApiCode
from app.feishu.core.larkClient import LarkClient
from app.feishu.core.types import ReplyPayload, SILENT_REPLY_TOKEN
from app.feishu.messaging.outbound.send import SendCardFeishuAsync, UpdateCardFeishuAsync
from common.cancellationToken import CancellationToken
from common.logger import Logger

# 对齐官方 shutdown-hooks：仅注册，进程/平台停止时 drain，绝不在注册时立刻执行
_shutdownHooks: dict[str, Any] = {}


def RegisterShutdownHook(key: str, callback: Any) -> Any:
    _shutdownHooks[key] = callback
    return lambda: _CancelShutdownHook(key)


def _CancelShutdownHook(key: str) -> None:
    _shutdownHooks.pop(key, None)


async def DrainShutdownHooksAsync() -> None:
    """平台停止时调用：依次 abort 未释放的流式卡片。"""
    items = list(_shutdownHooks.items())
    _shutdownHooks.clear()
    for key, callback in items:
        try:
            result = callback()
            if asyncio.iscoroutine(result):
                await result
        except Exception as err:
            Logger.Warning(f"shutdown hook failed key={key}: {err}")


def PrepareTerminalCardContent(
    text: str,
    imageResolver: ImageResolver,
    reasoningText: str | None = None,
    tableLimit: int = FEISHU_CARD_TABLE_LIMIT,
) -> dict[str, str | None]:
    resolvedReasoningText = imageResolver.ResolveImages(reasoningText) if reasoningText else None
    resolvedText = imageResolver.ResolveImages(text)
    segments = [resolvedReasoningText, resolvedText] if resolvedReasoningText else [resolvedText]
    sanitized = SanitizeTextSegmentsForCard(segments, tableLimit)
    if resolvedReasoningText:
        return {"reasoningText": sanitized[0], "text": sanitized[1]}
    return {"text": sanitized[0]}


class StreamingCardController:
    def __init__(self, deps: StreamingCardDeps) -> None:
        self._deps = deps
        self._phase = ECardPhase.IDLE
        self._cardKit = CardKitState()
        self._text = StreamingTextState()
        self._reasoning = ReasoningState()
        self._toolUse = ToolUseState()
        self._flush = FlushController(self._PerformFlushAsync)
        self._guard = UnavailableGuard(
            deps.replyToMessageId,
            lambda: self._cardKit.cardMessageId,
            lambda: self._Transition(ECardPhase.TERMINATED, "UnavailableGuard", "unavailable"),
        )
        self._imageResolver = ImageResolver(self._ScheduleImageResolvedUpdate)
        self._createEpoch = 0
        self._terminalReason: str | None = None
        self._dispatchFullyComplete = False
        self._pendingBodyReset = False
        self._cardCreationTask: asyncio.Task[None] | None = None
        self._disposeShutdownHook: Any | None = None
        self._dispatchStartTime = time.time() * 1000
        self._lastToolUseStatusUpdateTime = 0.0
        self._lastToolUseDisplayedFingerprint = ""
        self._trailingToolUseUpdateTask: asyncio.Task[None] | None = None
        self._lastFlushedReasoningText = ""
        self._lastReasoningFlushTime = 0.0
        self._reasoningPanelAttached = False
        self._cardApiLock = asyncio.Lock()

    @property
    def CardMessageId(self) -> str | None:
        return self._cardKit.cardMessageId

    @property
    def IsTerminalPhase(self) -> bool:
        return self._phase in TERMINAL_PHASES

    @property
    def IsAborted(self) -> bool:
        return self._phase == ECardPhase.ABORTED

    @property
    def IsTerminated(self) -> bool:
        return self._guard.IsTerminated

    @property
    def TerminalReason(self) -> str | None:
        return self._terminalReason

    def ShouldSkipForUnavailable(self, source: str) -> bool:
        return self._guard.ShouldSkip(source)

    def TerminateIfUnavailable(self, source: str, err: object | None = None) -> bool:
        return self._guard.Terminate(source, err)

    def MarkFullyComplete(self) -> None:
        self._dispatchFullyComplete = True

    def MarkPendingBodyReset(self) -> None:
        """标记：下一轮内容到达时先清空正文再绘制。"""
        self._pendingBodyReset = True

    async def EnsureCardCreatedAsync(self, cancellationToken: Optional[CancellationToken] = None) -> None:
        if self._guard.ShouldSkip("ensureCardCreated.precheck"):
            return
        if self._cardKit.cardMessageId or self._phase == ECardPhase.CREATION_FAILED or self.IsTerminalPhase:
            return
        if self._cardCreationTask is not None:
            await self._cardCreationTask
            return
        if not self._Transition(ECardPhase.CREATING, "ensureCardCreated"):
            return
        self._createEpoch += 1
        epoch = self._createEpoch
        self._cardCreationTask = asyncio.create_task(self._CreateCardAsync(epoch, cancellationToken))
        await self._cardCreationTask

    async def OnDeliverAsync(self, payload: ReplyPayload, cancellationToken: Optional[CancellationToken] = None) -> None:
        if not self._ShouldProceed("onDeliver"):
            return
        self._ResetBodyIfPending()
        text = payload.text or ""
        if not text.strip():
            return
        await self.EnsureCardCreatedAsync(cancellationToken)
        if not self._ShouldProceed("onDeliver.postCreate") or not self._cardKit.cardMessageId:
            return
        self._CaptureToolUseElapsed()
        split = SplitReasoningText(text)
        if split.get("reasoningText") and not split.get("answerText"):
            self._reasoning.reasoningElapsedMs = (
                time.time() * 1000 - self._reasoning.reasoningStartTime if self._reasoning.reasoningStartTime else 0
            )
            self._reasoning.accumulatedReasoningText = split["reasoningText"] or ""
            self._reasoning.isReasoningPhase = True
            await self._ThrottledCardUpdateAsync(cancellationToken)
            return
        self._reasoning.isReasoningPhase = False
        if split.get("reasoningText"):
            self._reasoning.accumulatedReasoningText = split["reasoningText"] or ""
        answerText = split.get("answerText") or text
        # 对齐 openclaw：completedText 始终 append deliver 载荷
        self._text.completedText += ("\n\n" if self._text.completedText else "") + answerText
        # 已有流式数据时不再改 accumulated / 刷 UI（partial 已负责）
        if not self._text.lastPartialText and not self._text.streamingPrefix:
            self._text.accumulatedText += ("\n\n" if self._text.accumulatedText else "") + answerText
            self._text.streamingPrefix = self._text.accumulatedText
            await self._ThrottledCardUpdateAsync(cancellationToken)

    async def OnReasoningStreamAsync(self, payload: ReplyPayload, cancellationToken: Optional[CancellationToken] = None) -> None:
        if not self._ShouldProceed("onReasoningStream"):
            return
        await self.EnsureCardCreatedAsync(cancellationToken)
        if not self._ShouldProceed("onReasoningStream.postCreate") or not self._cardKit.cardMessageId:
            return
        rawText = payload.text or ""
        if not rawText:
            return
        if self._reasoning.reasoningStartTime is None:
            self._reasoning.reasoningStartTime = time.time() * 1000
        self._reasoning.isReasoningPhase = True
        split = SplitReasoningText(rawText)
        self._reasoning.accumulatedReasoningText = split.get("reasoningText") or rawText
        await self._ThrottledCardUpdateAsync(cancellationToken)

    def CommitAnswerSegment(self) -> None:
        """工具轮次边界：固化当前 partial 段（等价 openclaw 长度缩短分界）。

        仅改 streamingPrefix / accumulatedText；completedText 只由 OnDeliver append，
        避免与 TEXT_COMPLETE 叠写重复。
        """
        if self._text.lastPartialText:
            self._text.streamingPrefix += (
                "\n\n" if self._text.streamingPrefix else ""
            ) + self._text.lastPartialText
            self._text.lastPartialText = ""
        elif self._text.accumulatedText and not self._text.streamingPrefix:
            self._text.streamingPrefix = self._text.accumulatedText
        self._text.accumulatedText = self._text.streamingPrefix

    async def OnToolStartAsync(
        self,
        payload: dict[str, str | None],
        cancellationToken: Optional[CancellationToken] = None,
    ) -> None:
        if not self._ShouldProceed("onToolStart") or not self._deps.toolUseDisplay.showToolUse:
            return
        self._ResetBodyIfPending()
        if payload.get("phase") and payload.get("phase") != "start":
            return
        # Commit 由 cardComponent._BeginToolRoundAsync 单点完成
        self._MarkToolUseActivity()
        await self.EnsureCardCreatedAsync(cancellationToken)
        if not self._ShouldProceed("onToolStart.postCreate") or not self._cardKit.cardMessageId:
            return
        # mango：双 element 下整卡回填正文安全，有无正文都刷工具区
        if self._cardKit.cardKitCardId:
            await self._ThrottledToolUseStatusUpdateAsync(cancellationToken)
            return
        await self._ThrottledCardUpdateAsync(cancellationToken)

    async def OnToolPayloadAsync(self, payload: ReplyPayload, cancellationToken: Optional[CancellationToken] = None) -> None:
        if not self._ShouldProceed("onToolPayload") or not self._deps.toolUseDisplay.showToolUse:
            return
        self._MarkToolUseActivity()
        await self.EnsureCardCreatedAsync(cancellationToken)
        if not self._ShouldProceed("onToolPayload.postCreate") or not self._cardKit.cardMessageId:
            return
        if self._cardKit.cardKitCardId:
            await self._ThrottledToolUseStatusUpdateAsync(cancellationToken)
            return
        await self._ThrottledCardUpdateAsync(cancellationToken)

    async def OnPartialReplyAsync(self, payload: ReplyPayload, cancellationToken: Optional[CancellationToken] = None) -> None:
        if not self._ShouldProceed("onPartialReply"):
            return
        self._ResetBodyIfPending()
        rawText = payload.text or ""
        split = SplitReasoningText(rawText)
        if split.get("reasoningText"):
            if self._reasoning.reasoningStartTime is None:
                self._reasoning.reasoningStartTime = time.time() * 1000
            self._reasoning.accumulatedReasoningText = split["reasoningText"] or ""
            self._reasoning.isReasoningPhase = True
        text = split.get("answerText") or StripReasoningTags(rawText)
        if not text:
            return
        self._CaptureToolUseElapsed()
        if self._reasoning.reasoningStartTime is None:
            self._reasoning.reasoningStartTime = time.time() * 1000
        if self._reasoning.isReasoningPhase:
            self._reasoning.isReasoningPhase = False
            self._reasoning.reasoningElapsedMs = (
                time.time() * 1000 - self._reasoning.reasoningStartTime if self._reasoning.reasoningStartTime else 0
            )
        if self._text.lastPartialText and len(text) < len(self._text.lastPartialText):
            self._text.streamingPrefix += ("\n\n" if self._text.streamingPrefix else "") + self._text.lastPartialText
        self._text.lastPartialText = text
        self._text.accumulatedText = (
            f"{self._text.streamingPrefix}\n\n{text}" if self._text.streamingPrefix else text
        )
        if not self._text.streamingPrefix and SILENT_REPLY_TOKEN.startswith(self._text.accumulatedText.strip()):
            return
        await self.EnsureCardCreatedAsync(cancellationToken)
        if not self._ShouldProceed("onPartialReply.postCreate") or not self._cardKit.cardMessageId:
            return
        await self._ThrottledCardUpdateAsync(cancellationToken)

    async def OnErrorAsync(
        self,
        err: object,
        info: dict[str, str],
        cancellationToken: Optional[CancellationToken] = None,
    ) -> None:
        if self._guard.Terminate("onError", err):
            return
        Logger.Error(f"{info.get('kind', 'reply')} reply failed: {err}")
        self._CaptureToolUseElapsed()
        self._FinalizeCard("onError", "error")
        await self._flush.WaitForFlushAsync()
        if self._cardCreationTask is not None:
            await self._cardCreationTask
        effectiveCardId = self._cardKit.cardKitCardId or self._cardKit.originalCardKitCardId
        footerMetrics = await self._GetFooterSessionMetricsAsync(cancellationToken)
        toolUseDisplay = self._ComputeToolUseDisplay()
        try:
            if self._cardKit.cardMessageId:
                rawErrorText = (
                    f"{self._text.accumulatedText}\n\n---\n**Error**: An error occurred while generating the response."
                    if self._text.accumulatedText
                    else "**Error**: An error occurred while generating the response."
                )
                terminalContent = PrepareTerminalCardContent(
                    rawErrorText,
                    self._imageResolver,
                    self._reasoning.accumulatedReasoningText or None,
                )
                errorCard = BuildCardContent(
                    "complete",
                    text=terminalContent["text"] or "",
                    reasoningText=terminalContent.get("reasoningText"),
                    reasoningElapsedMs=self._reasoning.reasoningElapsedMs or None,
                    toolUseSteps=toolUseDisplay.steps,
                    toolUseStepCount=toolUseDisplay.stepCount,
                    toolUseTitleSuffix=self._ComputeToolUseTitleSuffix(toolUseDisplay),
                    toolUseElapsedMs=self._VisibleToolUseElapsedMs(),
                    showToolUse=self._deps.toolUseDisplay.showToolUse,
                    elapsedMs=self._Elapsed(),
                    isError=True,
                    footer=self._deps.resolvedFooter,
                    footerMetrics=footerMetrics,
                )
                client = self._Client()
                if effectiveCardId:
                    await self._CloseStreamingAndUpdateAsync(client, effectiveCardId, errorCard, "onError", cancellationToken)
                else:
                    await UpdateCardFeishuAsync(client, self._cardKit.cardMessageId, errorCard, cancellationToken)
        except Exception:
            pass
        finally:
            ClearToolUseTraceRun(self._deps.sessionKey)

    async def OnIdleAsync(self, cancellationToken: Optional[CancellationToken] = None) -> None:
        if self._guard.IsTerminated or self._guard.ShouldSkip("onIdle"):
            return
        if not self._dispatchFullyComplete or self.IsTerminalPhase:
            return
        self._CaptureToolUseElapsed()
        self._FinalizeCard("onIdle", "normal")
        await self._flush.WaitForFlushAsync()
        if self._cardCreationTask is not None:
            await self._cardCreationTask
            await asyncio.sleep(0)
            await self._flush.WaitForFlushAsync()
        effectiveCardId = self._cardKit.cardKitCardId or self._cardKit.originalCardKitCardId
        client = self._Client()
        try:
            if not self._cardKit.cardMessageId:
                return
            isNoReplyLeak = not self._text.completedText and SILENT_REPLY_TOKEN.startswith(
                self._text.accumulatedText.strip()
            )
            displayText = (
                self._text.completedText
                or ("" if isNoReplyLeak else self._text.accumulatedText)
                or EMPTY_REPLY_FALLBACK_TEXT
            )
            resolvedDisplayText = await self._imageResolver.ResolveImagesAwaitAsync(
                displayText, 15000, cancellationToken
            )
            toolUseDisplay = self._ComputeToolUseDisplay()
            terminalContent = PrepareTerminalCardContent(
                resolvedDisplayText,
                self._imageResolver,
                self._reasoning.accumulatedReasoningText or None,
            )
            footerMetrics = await self._GetFooterSessionMetricsAsync(cancellationToken)
            completeCard = BuildCardContent(
                "complete",
                text=terminalContent["text"] or "",
                reasoningText=terminalContent.get("reasoningText"),
                reasoningElapsedMs=self._reasoning.reasoningElapsedMs or None,
                toolUseSteps=toolUseDisplay.steps,
                toolUseStepCount=toolUseDisplay.stepCount,
                toolUseTitleSuffix=self._ComputeToolUseTitleSuffix(toolUseDisplay),
                toolUseElapsedMs=self._VisibleToolUseElapsedMs(),
                showToolUse=self._deps.toolUseDisplay.showToolUse,
                elapsedMs=self._Elapsed(),
                footer=self._deps.resolvedFooter,
                footerMetrics=footerMetrics,
            )
            async with self._cardApiLock:
                if effectiveCardId:
                    self._cardKit.cardKitSequence += 1
                    await SetCardStreamingModeAsync(
                        client,
                        effectiveCardId,
                        False,
                        self._cardKit.cardKitSequence,
                        cancellationToken,
                    )
                    self._cardKit.cardKitSequence += 1
                    await UpdateCardKitCardAsync(
                        client,
                        effectiveCardId,
                        ToCardKit2(completeCard),
                        self._cardKit.cardKitSequence,
                        cancellationToken,
                    )
                else:
                    await UpdateCardFeishuAsync(
                        client, self._cardKit.cardMessageId, completeCard, cancellationToken
                    )
        except Exception as err:
            Logger.Warning(f"final card update failed: {err}")
        finally:
            ClearToolUseTraceRun(self._deps.sessionKey)

    async def AbortCardAsync(self, cancellationToken: Optional[CancellationToken] = None) -> None:
        try:
            self._CancelTrailingToolUseUpdate()
            self._CaptureToolUseElapsed()
            if not self._Transition(ECardPhase.ABORTED, "abortCard", "abort"):
                return
            await self._flush.WaitForFlushAsync()
            if self._cardCreationTask is not None:
                await self._cardCreationTask
            effectiveCardId = self._cardKit.cardKitCardId or self._cardKit.originalCardKitCardId
            toolUseDisplay = self._ComputeToolUseDisplay()
            terminalContent = PrepareTerminalCardContent(
                self._text.completedText or self._text.accumulatedText or "Aborted.",
                self._imageResolver,
                self._reasoning.accumulatedReasoningText or None,
            )
            footerMetrics = await self._GetFooterSessionMetricsAsync(cancellationToken)
            client = self._Client()
            abortCard = BuildCardContent(
                "complete",
                text=terminalContent["text"] or "",
                reasoningText=terminalContent.get("reasoningText"),
                reasoningElapsedMs=self._reasoning.reasoningElapsedMs or None,
                toolUseSteps=toolUseDisplay.steps,
                toolUseStepCount=toolUseDisplay.stepCount,
                toolUseTitleSuffix=self._ComputeToolUseTitleSuffix(toolUseDisplay),
                toolUseElapsedMs=self._VisibleToolUseElapsedMs(),
                showToolUse=self._deps.toolUseDisplay.showToolUse,
                elapsedMs=time.time() * 1000 - self._dispatchStartTime,
                isAborted=True,
                footer=self._deps.resolvedFooter,
                footerMetrics=footerMetrics,
            )
            if effectiveCardId:
                await self._CloseStreamingAndUpdateAsync(client, effectiveCardId, abortCard, "abortCard", cancellationToken)
            elif self._cardKit.cardMessageId:
                await UpdateCardFeishuAsync(client, self._cardKit.cardMessageId, abortCard, cancellationToken)
        except Exception as err:
            Logger.Warning(f"abortCard failed: {err}")
        finally:
            ClearToolUseTraceRun(self._deps.sessionKey)

    def _Client(self) -> LarkClient:
        return self._deps.client  # type: ignore[return-value]

    def _Elapsed(self) -> float:
        return time.time() * 1000 - self._dispatchStartTime

    def _NeedsFooterMetrics(self) -> bool:
        footer = self._deps.resolvedFooter
        # elapsed 用本地计时；tokens/cache 走 CLI 同源 GetLastTokenUsage
        return bool(footer.get("tokens") or footer.get("cache") or footer.get("context") or footer.get("model"))

    async def _GetFooterSessionMetricsAsync(
        self,
        cancellationToken: Optional[CancellationToken] = None,
    ) -> FooterSessionMetrics | None:
        if not self._NeedsFooterMetrics() or self._deps.getFooterMetrics is None:
            return None
        if cancellationToken is not None:
            cancellationToken.ThrowIfCancellationRequested()
        try:
            return await self._deps.getFooterMetrics()
        except Exception as err:
            Logger.Warning(f"footer metrics lookup failed: {err}")
            return None

    def _ShouldProceed(self, source: str) -> bool:
        if self._guard.IsTerminated or self._guard.ShouldSkip(source):
            return False
        return not self.IsTerminalPhase

    def _IsStaleCreate(self, epoch: int) -> bool:
        return epoch != self._createEpoch

    def _Transition(self, toPhase: ECardPhase, source: str, reason: str | None = None) -> bool:
        fromPhase = self._phase
        if fromPhase == toPhase:
            return False
        if toPhase not in PHASE_TRANSITIONS[fromPhase]:
            Logger.Warning(
                f"phase transition rejected from={CARD_PHASE_NAMES[fromPhase]} to={CARD_PHASE_NAMES[toPhase]} source={source}"
            )
            return False
        self._phase = toPhase
        Logger.Info(
            f"phase transition from={CARD_PHASE_NAMES[fromPhase]} to={CARD_PHASE_NAMES[toPhase]} source={source} reason={reason}"
        )
        if toPhase in TERMINAL_PHASES:
            self._terminalReason = reason
            self._OnEnterTerminalPhase()
        return True

    def _OnEnterTerminalPhase(self) -> None:
        self._createEpoch += 1
        self._flush.CancelPendingFlush()
        self._flush.Complete()
        if self._disposeShutdownHook:
            self._disposeShutdownHook()
            self._disposeShutdownHook = None
        if self._phase in (ECardPhase.TERMINATED, ECardPhase.CREATION_FAILED):
            ClearToolUseTraceRun(self._deps.sessionKey)

    def _MarkToolUseActivity(self) -> None:
        if self._toolUse.startedAt is None:
            self._toolUse.startedAt = time.time() * 1000
        self._toolUse.elapsedMs = time.time() * 1000 - self._toolUse.startedAt
        self._toolUse.isActive = True

    def _ResetBodyIfPending(self) -> None:
        """若上一轮 complete 已打标记，清空正文状态重新开始。"""
        if not self._pendingBodyReset:
            return
        self._pendingBodyReset = False
        self._text.completedText = ""
        self._text.accumulatedText = ""
        self._text.streamingPrefix = ""
        self._text.lastPartialText = ""
        self._text.lastFlushedText = ""

    def _CaptureToolUseElapsed(self) -> None:
        if self._toolUse.startedAt is None:
            return
        self._toolUse.elapsedMs = time.time() * 1000 - self._toolUse.startedAt
        self._toolUse.isActive = False

    def _ComputeToolUseDisplay(self) -> Any:
        if not self._deps.toolUseDisplay.showToolUse:
            return NormalizeToolUseDisplay([])
        # 卡片每条工具仅 1 行，不展开 result/error 块
        return NormalizeToolUseDisplay(
            GetToolUseTraceSteps(self._deps.sessionKey),
            showFullPaths=self._deps.toolUseDisplay.showFullPaths,
            showResultDetails=False,
        )

    def _VisibleToolUseElapsedMs(self) -> float | None:
        if not self._deps.toolUseDisplay.showToolUse or self._toolUse.startedAt is None:
            return None
        if self._toolUse.isActive:
            return time.time() * 1000 - self._toolUse.startedAt
        return self._toolUse.elapsedMs or (time.time() * 1000 - self._toolUse.startedAt)

    def _ComputeToolUseTitleSuffix(self, display: Any) -> dict[str, str] | None:
        if not self._deps.toolUseDisplay.showToolUse:
            return None
        stepCount = display.stepCount
        return BuildToolUseTitleSuffix(stepCount) if stepCount > 0 else None

    async def _CreateCardAsync(self, epoch: int, cancellationToken: Optional[CancellationToken] = None) -> None:
        client = self._Client()
        try:
            try:
                cardId = await CreateCardEntityAsync(
                    client,
                    BuildStreamingThinkingCard(self._deps.toolUseDisplay.showToolUse),
                    cancellationToken,
                )
                if self._IsStaleCreate(epoch):
                    return
                if not cardId:
                    raise RuntimeError("card.create returned empty card_id")
                self._cardKit.cardKitCardId = cardId
                self._cardKit.originalCardKitCardId = cardId
                self._cardKit.cardKitSequence = 1
                self._disposeShutdownHook = RegisterShutdownHook(f"streaming-card:{cardId}", self.AbortCardAsync)
                result = await SendCardByCardIdAsync(
                    client,
                    self._deps.chatId,
                    cardId,
                    self._deps.replyToMessageId,
                    cancellationToken,
                )
                if self._IsStaleCreate(epoch):
                    if self._disposeShutdownHook:
                        self._disposeShutdownHook()
                        self._disposeShutdownHook = None
                    return
                self._cardKit.cardMessageId = result.messageId
                self._flush.SetCardMessageReady(True)
                if not self._Transition(ECardPhase.STREAMING, "ensureCardCreated.cardkit"):
                    if self._disposeShutdownHook:
                        self._disposeShutdownHook()
                        self._disposeShutdownHook = None
            except Exception as cardKitErr:
                if self._IsStaleCreate(epoch):
                    return
                if self._guard.Terminate("ensureCardCreated.cardkitFlow", cardKitErr):
                    return
                Logger.Warning(f"CardKit flow failed, falling back to IM: {cardKitErr}")
                self._cardKit.cardKitCardId = None
                self._cardKit.originalCardKitCardId = None
                fallbackCard = BuildCardContent("streaming", showToolUse=self._deps.toolUseDisplay.showToolUse)
                result = await SendCardFeishuAsync(
                    client,
                    self._deps.chatId,
                    fallbackCard,
                    self._deps.replyToMessageId,
                    cancellationToken,
                )
                if self._IsStaleCreate(epoch):
                    return
                self._cardKit.cardMessageId = result.messageId
                self._flush.SetCardMessageReady(True)
                self._Transition(ECardPhase.STREAMING, "ensureCardCreated.imFallback")
        except Exception as err:
            if self._IsStaleCreate(epoch):
                return
            if self._guard.Terminate("ensureCardCreated.outer", err):
                return
            Logger.Warning(f"thinking card failed, falling back to static: {err}")
            self._Transition(ECardPhase.CREATION_FAILED, "ensureCardCreated.outer", "creation_failed")

    async def _PerformFlushAsync(self) -> None:
        """mango：思考 → 折叠面板内 reasoning_content；正文 → streaming_content。二者互不混写。"""
        if not self._cardKit.cardMessageId or self.IsTerminalPhase:
            return
        if not self._cardKit.cardKitCardId and self._cardKit.originalCardKitCardId:
            return
        client = self._Client()
        async with self._cardApiLock:
            try:
                answerText = self._imageResolver.ResolveImages(self._text.accumulatedText)
                reasoningText = TruncateReasoningForDisplay(self._reasoning.accumulatedReasoningText)
                answerChanged = answerText != self._text.lastFlushedText
                reasoningChanged = reasoningText != self._lastFlushedReasoningText
                if self._cardKit.cardKitCardId:
                    now = time.time() * 1000
                    # 思考栏单独节流；正文变化时可顺带刷思考，减少双 API 尖峰
                    reasoningDue = bool(reasoningText) and reasoningChanged and (
                        answerChanged
                        or now - self._lastReasoningFlushTime
                        >= THROTTLE_CONSTANTS["REASONING_CARDKIT_MS"]
                    )
                    syncedAnswerInRebuild = False
                    if reasoningDue and not self._reasoningPanelAttached:
                        # 首次思考：整卡挂上折叠思考区（此时才有 REASONING_ELEMENT_ID）
                        await self._RebuildStreamingCardAsync(
                            client,
                            reasoningText=reasoningText,
                            answerText=answerText,
                            includeReasoning=True,
                        )
                        self._reasoningPanelAttached = True
                        self._lastFlushedReasoningText = reasoningText
                        self._lastReasoningFlushTime = now
                        self._text.lastFlushedText = answerText
                        syncedAnswerInRebuild = True
                    elif reasoningDue:
                        self._cardKit.cardKitSequence += 1
                        await StreamCardContentAsync(
                            client,
                            self._cardKit.cardKitCardId,
                            REASONING_ELEMENT_ID,
                            reasoningText,
                            self._cardKit.cardKitSequence,
                        )
                        self._lastFlushedReasoningText = reasoningText
                        self._lastReasoningFlushTime = now
                    if answerChanged and not syncedAnswerInRebuild:
                        self._cardKit.cardKitSequence += 1
                        await StreamCardContentAsync(
                            client,
                            self._cardKit.cardKitCardId,
                            STREAMING_ELEMENT_ID,
                            OptimizeMarkdownStyle(answerText) if answerText else "",
                            self._cardKit.cardKitSequence,
                        )
                        self._text.lastFlushedText = answerText
                else:
                    flushDisplay = self._ComputeToolUseDisplay()
                    card = BuildCardContent(
                        "streaming",
                        text=answerText,
                        reasoningText=self._reasoning.accumulatedReasoningText or None,
                        toolUseSteps=flushDisplay.steps,
                        toolUseStepCount=flushDisplay.stepCount,
                        toolUseTitleSuffix=self._ComputeToolUseTitleSuffix(flushDisplay),
                        showToolUse=self._deps.toolUseDisplay.showToolUse,
                    )
                    await UpdateCardFeishuAsync(client, self._cardKit.cardMessageId, card)
            except Exception as err:
                if self._guard.Terminate("flushCardUpdate", err):
                    return
                if IsCardRateLimitError(err):
                    return
                if IsCardTableLimitError(err):
                    self._cardKit.cardKitCardId = None
                    return
                Logger.Error(f"card stream update failed code={ExtractLarkApiCode(err)}: {err}")
                if self._cardKit.cardKitCardId:
                    self._cardKit.cardKitCardId = None

    async def _RebuildStreamingCardAsync(
        self,
        client: LarkClient,
        reasoningText: str,
        answerText: str,
        includeReasoning: bool,
        cancellationToken: Optional[CancellationToken] = None,
    ) -> None:
        """整卡重建流式骨架（工具区 / 折叠思考区），并带回已累积正文避免被清空。"""
        if not self._cardKit.cardKitCardId:
            return
        display = self._ComputeToolUseDisplay()
        card = BuildStreamingPreAnswerCard(
            steps=display.steps,
            elapsedMs=self._VisibleToolUseElapsedMs(),
            showToolUse=self._deps.toolUseDisplay.showToolUse,
            totalStepCount=display.stepCount,
            reasoningText=reasoningText,
            answerText=answerText,
            includeReasoning=includeReasoning,
        )
        self._cardKit.cardKitSequence += 1
        await UpdateCardKitCardAsync(
            client,
            self._cardKit.cardKitCardId,
            card,
            self._cardKit.cardKitSequence,
            cancellationToken,
        )

    async def _ThrottledCardUpdateAsync(self, cancellationToken: Optional[CancellationToken] = None) -> None:
        if self._guard.ShouldSkip("throttledCardUpdate"):
            return
        throttleMs = THROTTLE_CONSTANTS["CARDKIT_MS"] if self._cardKit.cardKitCardId else THROTTLE_CONSTANTS["PATCH_MS"]
        await self._flush.ThrottledUpdateAsync(throttleMs)

    def _ToolUseDisplayFingerprint(self, display: Any) -> str:
        parts = [f"{display.stepCount}"]
        for step in display.steps or []:
            parts.append(f"{step.status}:{step.title}:{step.detail or ''}")
        return "|".join(parts)

    async def _ThrottledToolUseStatusUpdateAsync(self, cancellationToken: Optional[CancellationToken] = None) -> None:
        if not self._cardKit.cardKitCardId:
            return
        display = self._ComputeToolUseDisplay()
        fingerprint = self._ToolUseDisplayFingerprint(display)
        force = fingerprint != self._lastToolUseDisplayedFingerprint
        now = time.time() * 1000
        if not force and now - self._lastToolUseStatusUpdateTime < THROTTLE_CONSTANTS["TOOL_STATUS_MS"]:
            self._ScheduleTrailingToolUseUpdate(cancellationToken)
            return
        self._CancelTrailingToolUseUpdate()
        self._lastToolUseStatusUpdateTime = now
        await self._UpdateToolUseStatusAsync(cancellationToken)

    def _ScheduleTrailingToolUseUpdate(self, cancellationToken: Optional[CancellationToken] = None) -> None:
        """节流窗口内的事件合并为窗口结束后补刷一帧，避免结束态漏刷新。"""
        if self._trailingToolUseUpdateTask is not None and not self._trailingToolUseUpdateTask.done():
            return
        delaySec = THROTTLE_CONSTANTS["TOOL_STATUS_MS"] / 1000

        async def _Run() -> None:
            try:
                await asyncio.sleep(delaySec)
                if self.IsTerminalPhase or not self._cardKit.cardKitCardId:
                    return
                self._lastToolUseStatusUpdateTime = time.time() * 1000
                await self._UpdateToolUseStatusAsync(cancellationToken)
            except asyncio.CancelledError:
                return
            except Exception as err:
                Logger.Debug(f"trailing toolUse update failed: {err}")

        self._trailingToolUseUpdateTask = asyncio.create_task(_Run())

    def _CancelTrailingToolUseUpdate(self) -> None:
        task = self._trailingToolUseUpdateTask
        self._trailingToolUseUpdateTask = None
        if task is not None and not task.done():
            task.cancel()

    async def _UpdateToolUseStatusAsync(self, cancellationToken: Optional[CancellationToken] = None) -> None:
        if not self._cardKit.cardKitCardId or self.IsTerminalPhase:
            return
        # 与 performFlush 共用锁，避免 sequence 冲突
        await self._flush.WaitForFlushAsync()
        async with self._cardApiLock:
            if not self._cardKit.cardKitCardId or self.IsTerminalPhase:
                return
            try:
                display = self._ComputeToolUseDisplay()
                # 无工具步骤时不必整卡刷新（避免空 pending）；有步骤才重建
                if not display.steps:
                    return
                answerText = self._imageResolver.ResolveImages(self._text.accumulatedText)
                reasoningText = TruncateReasoningForDisplay(self._reasoning.accumulatedReasoningText)
                includeReasoning = self._reasoningPanelAttached or bool(reasoningText)
                await self._RebuildStreamingCardAsync(
                    self._Client(),
                    reasoningText=reasoningText,
                    answerText=answerText,
                    includeReasoning=includeReasoning,
                    cancellationToken=cancellationToken,
                )
                if includeReasoning:
                    self._reasoningPanelAttached = True
                self._lastFlushedReasoningText = reasoningText
                self._text.lastFlushedText = answerText
                self._lastToolUseDisplayedFingerprint = self._ToolUseDisplayFingerprint(display)
            except Exception as err:
                if IsCardRateLimitError(err):
                    return
                Logger.Warning(f"updateToolUseStatus failed: {err}")

    def _FinalizeCard(self, source: str, reason: str) -> None:
        self._CancelTrailingToolUseUpdate()
        self._Transition(ECardPhase.COMPLETED, source, reason)

    async def _CloseStreamingAndUpdateAsync(
        self,
        client: LarkClient,
        cardId: str,
        card: dict[str, object],
        label: str,
        cancellationToken: Optional[CancellationToken] = None,
    ) -> None:
        async with self._cardApiLock:
            self._cardKit.cardKitSequence += 1
            await SetCardStreamingModeAsync(
                client, cardId, False, self._cardKit.cardKitSequence, cancellationToken
            )
            self._cardKit.cardKitSequence += 1
            await UpdateCardKitCardAsync(
                client, cardId, ToCardKit2(card), self._cardKit.cardKitSequence, cancellationToken
            )

    def _ScheduleImageResolvedUpdate(self) -> None:
        if not self.IsTerminalPhase and self._cardKit.cardMessageId:
            asyncio.create_task(self._ThrottledCardUpdateAsync())
