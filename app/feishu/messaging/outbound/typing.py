"""Typing Indicator：通过表情反应模拟"正在输入"状态。

飞书没有原生的 typing indicator API。本模块在用户消息上添加一个
"Typing" 表情反应作为视觉提示（表示 bot 已收到消息且在处理），
回复完成后自动移除。

对齐 openclaw-lark-main src/messaging/outbound/typing.ts。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from app.feishu.core.larkClient import LarkClient
from app.feishu.core.messageUnavailable import (
    IsMessageUnavailableError,
    RunWithMessageUnavailableGuardAsync,
)
from app.feishu.core.targets import NormalizeMessageId
from common.cancellationToken import CancellationToken
from common.logger import Logger

# "Typing" 是飞书内置表情，显示铅笔/键盘动画，自然适合作为输入提示
TYPING_EMOJI_TYPE = "Typing"


@dataclass
class TypingIndicatorState:
    """当前 typing indicator 状态，用于后续移除。"""

    messageId: str
    """已添加反应的消息 ID（规范化后）。"""
    reactionId: str | None = None
    """飞书返回的 reaction_id，None 表示添加失败。"""


async def AddTypingIndicatorAsync(
    client: LarkClient,
    messageId: str,
    cancellationToken: Optional[CancellationToken] = None,
) -> TypingIndicatorState:
    """给用户消息添加 "Typing" 表情反应。

    静默失败：网络问题、权限不足、限流等情况仅记录日志，
    不向上抛异常，确保 typing indicator 永远不阻塞消息处理。
    """
    normalizedId = NormalizeMessageId(messageId)
    state = TypingIndicatorState(messageId=normalizedId)

    try:
        reactionId = await RunWithMessageUnavailableGuardAsync(
            normalizedId,
            "im.messageReaction.create(typing)",
            lambda: client.AddReactionAsync(
                normalizedId,
                TYPING_EMOJI_TYPE,
                cancellationToken=cancellationToken,
            ),
        )
        state.reactionId = reactionId
    except Exception as err:
        if IsMessageUnavailableError(err):
            Logger.Debug(f"Skip add typing indicator for unavailable message id={normalizedId}")
            return state
        # 静默吞错：typing indicator 是尽力而为的视觉提示
        msg = str(err)
        Logger.Debug(f"Failed to add typing indicator messageId={messageId} error={msg}")

    return state


async def RemoveTypingIndicatorAsync(
    client: LarkClient,
    state: TypingIndicatorState,
    cancellationToken: Optional[CancellationToken] = None,
) -> None:
    """移除之前添加的 typing indicator 表情反应。

    若 reactionId 为空（表示从未成功添加），则直接返回。
    失败静默吞错 —— 残留的表情反应不会造成用户困扰。
    """
    if not state.reactionId:
        return

    try:
        await RunWithMessageUnavailableGuardAsync(
            state.messageId,
            "im.messageReaction.delete(typing)",
            lambda: client.DeleteReactionAsync(
                state.messageId,
                state.reactionId,
                cancellationToken=cancellationToken,
            ),
        )
    except Exception as err:
        if IsMessageUnavailableError(err):
            Logger.Debug(f"Skip remove typing indicator for unavailable message id={state.messageId}")
            return
        msg = str(err)
        Logger.Debug(f"Failed to remove typing indicator messageId={state.messageId} error={msg}")
