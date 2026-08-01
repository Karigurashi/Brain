"""飞书 reply dispatcher 工厂。"""

from __future__ import annotations

from typing import Optional

from app.feishu.card.builder import SplitReasoningText, StripReasoningTags
from app.feishu.card.cardError import IsCardTableLimitError
from app.feishu.card.replyDispatcherTypes import (
    CreateFeishuReplyDispatcherParams,
    FeishuReplyDispatcherResult,
    ReplyDispatcherCallbacks,
    StreamingCardDeps,
)
from app.feishu.card.replyMode import ExpandAutoMode, ResolveReplyMode, ShouldUseCard
from app.feishu.card.streamingCardController import StreamingCardController
from app.feishu.card.unavailableGuard import UnavailableGuard
from app.feishu.core.footerConfig import ResolveFooterConfig
from app.feishu.core.larkClient import LarkClient
from app.feishu.core.types import FeishuCredentials, ReplyPayload
from app.feishu.messaging.outbound.send import (
    SendMarkdownCardFeishuAsync,
    SendMessageFeishuAsync,
)
from app.feishu.messaging.outbound.typing import (
    AddTypingIndicatorAsync,
    RemoveTypingIndicatorAsync,
    TypingIndicatorState,
)
from common.cancellationToken import CancellationToken
from common.logger import Logger


def CreateFeishuReplyDispatcher(params: CreateFeishuReplyDispatcherParams) -> FeishuReplyDispatcherResult:
    credentials = params.credentials
    if not isinstance(credentials, LarkClient):
        if isinstance(credentials, FeishuCredentials):
            client = LarkClient.FromCredentials(credentials)
        else:
            raise TypeError("credentials must be LarkClient or FeishuCredentials")
    else:
        client = credentials

    feishuCfg = params.feishuCfg
    effectiveReplyMode = ResolveReplyMode(feishuCfg, params.chatType)
    replyMode = ExpandAutoMode(
        effectiveReplyMode,
        feishuCfg.streaming if feishuCfg else None,
        params.chatType,
    )
    useStreamingCards = replyMode == "streaming"
    resolvedFooter = ResolveFooterConfig(feishuCfg.footer if feishuCfg else None)
    textChunkLimit = params.textChunkLimit

    controller = (
        StreamingCardController(
            StreamingCardDeps(
                client=client,
                agentId=params.agentId,
                sessionKey=params.sessionKey,
                accountId=params.accountId,
                chatId=params.chatId,
                replyToMessageId=params.replyToMessageId,
                toolUseDisplay=params.toolUseDisplay,
                resolvedFooter=resolvedFooter,
                getFooterMetrics=params.getFooterMetrics,
            )
        )
        if useStreamingCards
        else None
    )

    staticAborted = False
    staticGuard = (
        None
        if controller
        else UnavailableGuard(
            params.replyToMessageId,
            lambda: None,
            lambda: _SetStaticAborted(),
        )
    )

    def _SetStaticAborted() -> None:
        nonlocal staticAborted
        staticAborted = True

    def _ShouldSkip(source: str) -> bool:
        if controller:
            return controller.ShouldSkipForUnavailable(source)
        return staticGuard.ShouldSkip(source) if staticGuard else False

    def _IsTerminated() -> bool:
        if controller:
            return controller.IsTerminated
        return staticGuard.IsTerminated if staticGuard else False

    dispatchFullyComplete = False
    dispatchIdle = False

    # ---- Typing Indicator（对齐 openclaw-lark-main） ----
    typingState: TypingIndicatorState | None = None
    typingStopped = False

    async def _StartTypingAsync() -> None:
        """添加 Typing 表情反应作为「正在处理」视觉提示。"""
        nonlocal typingState, typingStopped
        if _ShouldSkip("typing.start"):
            return
        if not params.replyToMessageId or typingStopped or params.skipTyping:
            return
        if typingState and typingState.reactionId:
            return
        typingState = await AddTypingIndicatorAsync(
            client,
            params.replyToMessageId,
            cancellationToken=None,
        )
        if typingStopped and typingState and typingState.reactionId:
            await RemoveTypingIndicatorAsync(client, typingState)
            typingState = None
            Logger.Debug("typing indicator removed (raced with stop)")

    async def _StopTypingAsync() -> None:
        """移除 Typing 表情反应。"""
        nonlocal typingStopped, typingState
        typingStopped = True
        if not typingState:
            return
        await RemoveTypingIndicatorAsync(client, typingState)
        typingState = None

    async def _OnReplyStartAsync(cancellationToken: Optional[CancellationToken] = None) -> None:
        if _ShouldSkip("onReplyStart"):
            return
        await _StartTypingAsync()

    async def _DeliverAsync(
        payload: ReplyPayload,
        meta: dict[str, str] | None = None,
        cancellationToken: Optional[CancellationToken] = None,
    ) -> None:
        if _ShouldSkip("deliver.entry"):
            return
        if staticAborted or (controller and (controller.IsTerminated or controller.IsAborted)):
            return
        if dispatchFullyComplete:
            return

        text = _GetVisiblePayloadText(payload)
        reasoningText = payload.text if payload.isReasoning else ""
        mediaUrls = payload.mediaUrls or ([payload.mediaUrl] if payload.mediaUrl else [])
        if not text.strip() and not reasoningText.strip() and not mediaUrls:
            return

        # 工具结果只刷新工具区，绝不落入正文 / 静态消息
        if meta and meta.get("kind") == "tool":
            if (
                controller
                and params.toolUseDisplay.showToolUse
                and _ShouldRouteToolPayloadToCard(payload, True)
            ):
                await controller.OnToolPayloadAsync(payload, cancellationToken)
            return

        if controller:
            controllerText = reasoningText.strip() or text
            if controllerText.strip():
                await controller.EnsureCardCreatedAsync(cancellationToken)
                if controller.IsTerminated:
                    return
                if controller.CardMessageId:
                    if payload.isReasoning:
                        await controller.OnReasoningStreamAsync(
                            ReplyPayload(text=controllerText, isReasoning=True),
                            cancellationToken,
                        )
                        return
                    await controller.OnDeliverAsync(ReplyPayload(text=controllerText), cancellationToken)
                    return
                Logger.Warning("deliver: card creation failed, falling back to static delivery")

        if text.strip():
            chunks = _ChunkText(text, textChunkLimit)
            cardTableLimitHit = False
            for chunk in chunks:
                if cardTableLimitHit:
                    try:
                        await SendMessageFeishuAsync(
                            client,
                            params.chatId,
                            chunk,
                            params.replyToMessageId,
                            cancellationToken,
                        )
                    except Exception as fallbackErr:
                        if staticGuard and staticGuard.Terminate("deliver.textFallback", fallbackErr):
                            return
                        raise
                    continue
                if ShouldUseCard(chunk):
                    try:
                        await SendMarkdownCardFeishuAsync(
                            client,
                            params.chatId,
                            chunk,
                            params.replyToMessageId,
                            cancellationToken,
                        )
                    except Exception as err:
                        if staticGuard and staticGuard.Terminate("deliver.cardChunk", err):
                            return
                        if IsCardTableLimitError(err):
                            cardTableLimitHit = True
                            await SendMessageFeishuAsync(
                                client,
                                params.chatId,
                                chunk,
                                params.replyToMessageId,
                                cancellationToken,
                            )
                            continue
                        raise
                else:
                    try:
                        await SendMessageFeishuAsync(
                            client,
                            params.chatId,
                            chunk,
                            params.replyToMessageId,
                            cancellationToken,
                        )
                    except Exception as err:
                        if staticGuard and staticGuard.Terminate("deliver.textChunk", err):
                            return
                        raise

    async def _OnErrorAsync(
        err: object,
        info: dict[str, str],
        cancellationToken: Optional[CancellationToken] = None,
    ) -> None:
        await _StopTypingAsync()
        if controller:
            if controller.TerminateIfUnavailable("onError", err):
                return
            await controller.OnErrorAsync(err, info, cancellationToken)
            return
        if staticGuard and staticGuard.Terminate("onError", err):
            return
        Logger.Error(f"{info.get('kind', 'reply')} reply failed: {err}")

    async def _OnIdleAsync(cancellationToken: Optional[CancellationToken] = None) -> None:
        if _IsTerminated() or _ShouldSkip("onIdle"):
            await _StopTypingAsync()
            return
        if not dispatchFullyComplete:
            await _StopTypingAsync()
            return
        if controller:
            await controller.OnIdleAsync(cancellationToken)
        await _StopTypingAsync()

    async def _OnCleanupAsync(cancellationToken: Optional[CancellationToken] = None) -> None:
        await _StopTypingAsync()

    def _MarkDispatchIdle() -> None:
        nonlocal dispatchIdle
        dispatchIdle = True

    def _MarkFullyComplete() -> None:
        nonlocal dispatchFullyComplete
        dispatchFullyComplete = True
        if controller:
            controller.MarkFullyComplete()

    async def _AbortCardAsync(cancellationToken: Optional[CancellationToken] = None) -> None:
        if controller:
            await controller.AbortCardAsync(cancellationToken)

    replyOptions: dict[str, object] = {}
    if controller:
        replyOptions.update(
            {
                "shouldEmitToolResult": lambda: False,
                "shouldEmitToolOutput": lambda: False,
                "onReasoningStream": lambda payload: controller.OnReasoningStreamAsync(payload),
                "onPartialReply": lambda payload: controller.OnPartialReplyAsync(payload),
                "onToolStart": lambda payload: controller.OnToolStartAsync(payload),
                "onToolPayload": lambda payload: controller.OnToolPayloadAsync(payload),
                "onCommitAnswerSegment": lambda: controller.CommitAnswerSegment(),
                "markPendingBodyReset": lambda: controller.MarkPendingBodyReset(),
            }
        )

    return FeishuReplyDispatcherResult(
        dispatcher=ReplyDispatcherCallbacks(
            deliver=_DeliverAsync,
            onError=_OnErrorAsync,
            onIdle=_OnIdleAsync,
            onReplyStart=_OnReplyStartAsync,
            onCleanup=_OnCleanupAsync,
        ),
        replyOptions=replyOptions,
        markDispatchIdle=_MarkDispatchIdle,
        markFullyComplete=_MarkFullyComplete,
        abortCard=_AbortCardAsync,
    )


def _GetVisiblePayloadText(payload: ReplyPayload) -> str:
    if payload.isReasoning:
        return ""
    rawText = payload.text or ""
    if not rawText:
        return ""
    split = SplitReasoningText(rawText)
    if split.get("answerText") is not None:
        return split["answerText"] or ""
    return StripReasoningTags(rawText)


def _ShouldRouteToolPayloadToCard(payload: ReplyPayload, showToolUse: bool) -> bool:
    if not showToolUse:
        return False
    if not _GetVisiblePayloadText(payload).strip():
        return False
    if payload.interactive or payload.btw or payload.audioAsVoice:
        return False
    if payload.mediaUrl or payload.mediaUrls:
        return False
    if payload.channelData and isinstance(payload.channelData, dict):
        execApproval = payload.channelData.get("execApproval")
        if isinstance(execApproval, dict):
            return False
    return True


def _ChunkText(text: str, limit: int) -> list[str]:
    if len(text) <= limit:
        return [text]
    chunks: list[str] = []
    start = 0
    while start < len(text):
        chunks.append(text[start : start + limit])
        start += limit
    return chunks
