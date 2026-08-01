"""飞书 outbound 卡片发送原语。"""

from __future__ import annotations

from typing import Any, Optional

from app.feishu.card.markdownStyle import OptimizeMarkdownStyle
from app.feishu.core.larkClient import LarkClient
from app.feishu.core.messageUnavailable import RunWithMessageUnavailableGuardAsync
from app.feishu.core.targets import NormalizeMessageId
from app.feishu.messaging.types import FeishuSendResult
from common.cancellationToken import CancellationToken


async def SendCardFeishuAsync(
    client: LarkClient,
    to: str,
    card: dict[str, Any],
    replyToMessageId: str | None = None,
    cancellationToken: Optional[CancellationToken] = None,
) -> FeishuSendResult:
    normalizedId = NormalizeMessageId(replyToMessageId)

    async def _Send() -> dict[str, str]:
        return await client.SendInteractiveMessageAsync(to, card, replyToMessageId, cancellationToken=cancellationToken)

    if normalizedId:
        result = await RunWithMessageUnavailableGuardAsync(normalizedId, "im.message.reply(interactive)", _Send)
    else:
        result = await _Send()
    return FeishuSendResult(messageId=result["messageId"], chatId=result["chatId"])


async def UpdateCardFeishuAsync(
    client: LarkClient,
    messageId: str,
    card: dict[str, Any],
    cancellationToken: Optional[CancellationToken] = None,
) -> None:
    await RunWithMessageUnavailableGuardAsync(
        messageId,
        "im.message.patch(interactive)",
        lambda: client.PatchInteractiveMessageAsync(messageId, card, cancellationToken=cancellationToken),
    )


def BuildMarkdownCard(text: str) -> dict[str, Any]:
    optimizedText = OptimizeMarkdownStyle(text)
    return {
        "schema": "2.0",
        "config": {"wide_screen_mode": True},
        "body": {"elements": [{"tag": "markdown", "content": optimizedText}]},
    }


async def SendMarkdownCardFeishuAsync(
    client: LarkClient,
    to: str,
    text: str,
    replyToMessageId: str | None = None,
    cancellationToken: Optional[CancellationToken] = None,
) -> FeishuSendResult:
    card = BuildMarkdownCard(text)
    return await SendCardFeishuAsync(client, to, card, replyToMessageId, cancellationToken)


async def SendMessageFeishuAsync(
    client: LarkClient,
    to: str,
    text: str,
    replyToMessageId: str | None = None,
    cancellationToken: Optional[CancellationToken] = None,
) -> FeishuSendResult:
    result = await client.SendPostMessageAsync(to, text, replyToMessageId, cancellationToken=cancellationToken)
    return FeishuSendResult(messageId=result["messageId"], chatId=result["chatId"])
