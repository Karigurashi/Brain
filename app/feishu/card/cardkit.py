"""CardKit 流式 API 封装。"""

from __future__ import annotations

from typing import Any, Optional

from app.feishu.core.larkClient import LarkClient
from app.feishu.core.messageUnavailable import RunWithMessageUnavailableGuardAsync
from app.feishu.core.targets import NormalizeMessageId
from app.feishu.messaging.types import FeishuSendResult
from common.cancellationToken import CancellationToken
from common.logger import Logger


async def CreateCardEntityAsync(
    client: LarkClient,
    card: dict[str, Any],
    cancellationToken: Optional[CancellationToken] = None,
) -> str | None:
    cardId = await client.CreateCardEntityAsync(card, cancellationToken=cancellationToken)
    Logger.Info(f"cardkit card.create cardId={cardId}")
    return cardId


async def StreamCardContentAsync(
    client: LarkClient,
    cardId: str,
    elementId: str,
    content: str,
    sequence: int,
    cancellationToken: Optional[CancellationToken] = None,
) -> None:
    await client.StreamCardContentAsync(cardId, elementId, content, sequence, cancellationToken=cancellationToken)


async def UpdateCardKitCardAsync(
    client: LarkClient,
    cardId: str,
    card: dict[str, Any],
    sequence: int,
    cancellationToken: Optional[CancellationToken] = None,
) -> None:
    await client.UpdateCardKitCardAsync(cardId, card, sequence, cancellationToken=cancellationToken)


async def SendCardByCardIdAsync(
    client: LarkClient,
    to: str,
    cardId: str,
    replyToMessageId: str | None = None,
    cancellationToken: Optional[CancellationToken] = None,
) -> FeishuSendResult:
    normalizedId = NormalizeMessageId(replyToMessageId)

    async def _Send() -> dict[str, str]:
        return await client.SendCardByCardIdAsync(to, cardId, replyToMessageId, cancellationToken=cancellationToken)

    if normalizedId:
        result = await RunWithMessageUnavailableGuardAsync(
            normalizedId,
            "im.message.reply(interactive.cardkit)",
            _Send,
        )
    else:
        result = await _Send()
    return FeishuSendResult(messageId=result["messageId"], chatId=result["chatId"])


async def SetCardStreamingModeAsync(
    client: LarkClient,
    cardId: str,
    streamingMode: bool,
    sequence: int,
    cancellationToken: Optional[CancellationToken] = None,
) -> None:
    await client.SetCardStreamingModeAsync(cardId, streamingMode, sequence, cancellationToken=cancellationToken)
