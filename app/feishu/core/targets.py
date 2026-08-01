"""飞书目标 ID 解析与格式化。"""

from __future__ import annotations

import re
from typing import Literal, Optional
from urllib.parse import parse_qs, urlencode

from app.feishu.core.types import FeishuIdType

CHAT_PREFIX = "oc_"
OPEN_ID_PREFIX = "ou_"
TAG_CHAT = "chat:"
TAG_USER = "user:"
TAG_OPEN_ID = "open_id:"
TAG_FEISHU = "feishu:"
ROUTE_META_FRAGMENT_REPLY_TO = "__feishu_reply_to"


def DetectIdType(idValue: str) -> Optional[FeishuIdType]:
    if not idValue:
        return None
    if idValue.startswith(CHAT_PREFIX):
        return "chat_id"
    if idValue.startswith(OPEN_ID_PREFIX):
        return "open_id"
    if re.fullmatch(r"[a-zA-Z0-9]+", idValue):
        return "user_id"
    return None


def ParseFeishuRouteTarget(raw: str) -> dict[str, Optional[str]]:
    trimmed = raw.strip()
    if not trimmed:
        return {"target": ""}
    hashIndex = trimmed.find("#")
    if hashIndex < 0:
        return {"target": trimmed}
    target = trimmed[:hashIndex].strip()
    fragment = trimmed[hashIndex + 1 :].strip()
    if not fragment:
        return {"target": target}
    params = parse_qs(fragment, keep_blank_values=False)
    replyValues = params.get(ROUTE_META_FRAGMENT_REPLY_TO)
    replyToMessageId = NormalizeMessageId(replyValues[0] if replyValues else None)
    return {
        "target": target,
        "replyToMessageId": replyToMessageId,
    }


def NormalizeFeishuTarget(raw: str) -> Optional[str]:
    if not raw:
        return None
    parsed = ParseFeishuRouteTarget(raw)
    trimmed = parsed["target"].strip()
    if not trimmed:
        return None
    if trimmed.startswith(TAG_FEISHU):
        inner = trimmed[len(TAG_FEISHU) :].strip()
        if inner:
            return inner
    if trimmed.startswith(TAG_CHAT):
        return trimmed[len(TAG_CHAT) :]
    if trimmed.startswith(TAG_USER):
        return trimmed[len(TAG_USER) :]
    if trimmed.startswith(TAG_OPEN_ID):
        return trimmed[len(TAG_OPEN_ID) :]
    return trimmed


def EncodeFeishuRouteTarget(target: str, replyToMessageId: Optional[str] = None) -> str:
    trimmed = target.strip()
    if not trimmed:
        return trimmed
    normalizedReply = NormalizeMessageId(replyToMessageId.strip() if replyToMessageId else None)
    if not normalizedReply:
        return trimmed
    fragment = urlencode({ROUTE_META_FRAGMENT_REPLY_TO: normalizedReply})
    return f"{trimmed}#{fragment}"


def FormatFeishuTarget(idValue: str, idType: Optional[FeishuIdType] = None) -> str:
    resolved = idType or DetectIdType(idValue)
    if resolved == "chat_id":
        return f"{TAG_CHAT}{idValue}"
    return f"{TAG_USER}{idValue}"


def ResolveReceiveIdType(idValue: str) -> Literal["chat_id", "open_id", "user_id"]:
    if idValue.startswith(CHAT_PREFIX):
        return "chat_id"
    if idValue.startswith(OPEN_ID_PREFIX):
        return "open_id"
    return "open_id"


def NormalizeMessageId(messageId: str) -> str: ...


def NormalizeMessageId(messageId: Optional[str]) -> Optional[str]: ...


def NormalizeMessageId(messageId: Optional[str]) -> Optional[str]:
    if not messageId:
        return None
    colonIndex = messageId.find(":")
    if colonIndex >= 0:
        return messageId[:colonIndex]
    return messageId


def LooksLikeFeishuId(raw: str) -> bool:
    if not raw:
        return False
    return (
        raw.startswith(TAG_CHAT)
        or raw.startswith(TAG_USER)
        or raw.startswith(TAG_OPEN_ID)
        or raw.startswith(CHAT_PREFIX)
        or raw.startswith(OPEN_ID_PREFIX)
    )
