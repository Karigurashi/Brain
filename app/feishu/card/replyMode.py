"""Reply mode 解析。"""

from __future__ import annotations

from typing import Literal, Union

from app.feishu.card.cardError import FEISHU_CARD_TABLE_LIMIT, FindMarkdownTablesOutsideCodeBlocks
from app.feishu.core.types import FeishuConfig, FeishuReplyModeConfig, ReplyModeValue

ConcreteReplyMode = Literal["static", "streaming"]


def ResolveReplyMode(feishuCfg: FeishuConfig | None, chatType: str | None = None) -> ReplyModeValue:
    if not feishuCfg or feishuCfg.streaming is not True:
        return "static"
    replyMode = feishuCfg.replyMode
    if replyMode is None:
        return "auto"
    if isinstance(replyMode, str):
        return replyMode
    sceneMode: ReplyModeValue | None = None
    if chatType == "group":
        sceneMode = replyMode.group
    elif chatType == "p2p":
        sceneMode = replyMode.direct
    return sceneMode or replyMode.default or "auto"


def ExpandAutoMode(
    mode: ReplyModeValue,
    streaming: bool | None,
    chatType: str | None = None,
) -> ConcreteReplyMode:
    if mode != "auto":
        return mode  # type: ignore[return-value]
    if streaming is True:
        return "static" if chatType == "group" else "streaming"
    return "static"


def ShouldUseCard(text: str) -> bool:
    tableMatches = FindMarkdownTablesOutsideCodeBlocks(text)
    if len(tableMatches) > FEISHU_CARD_TABLE_LIMIT:
        return False
    return False
