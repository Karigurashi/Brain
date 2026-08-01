"""飞书 outbound 消息类型。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class FeishuSendResult:
    messageId: str
    chatId: str
    warning: str | None = None
