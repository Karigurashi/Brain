"""飞书通道核心类型定义。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Optional, Union


LarkBrand = Union[Literal["feishu"], Literal["lark"], str]
FeishuIdType = Literal["open_id", "user_id", "union_id", "chat_id"]
ChatType = Literal["p2p", "group"]
ReplyModeValue = Literal["auto", "static", "streaming"]
ToolUseMode = Literal["off", "on", "full"]


@dataclass
class FeishuCredentials:
    appId: str = ""
    appSecret: str = ""
    brand: LarkBrand = "feishu"
    accountId: str = "default"


@dataclass
class FeishuFooterConfig:
    status: Optional[bool] = None
    elapsed: Optional[bool] = None
    tokens: Optional[bool] = None
    cache: Optional[bool] = None
    context: Optional[bool] = None
    model: Optional[bool] = None


@dataclass
class FeishuToolUseDisplayConfig:
    showFullPaths: Optional[bool] = None


@dataclass
class FeishuReplyModeConfig:
    default: Optional[ReplyModeValue] = None
    group: Optional[ReplyModeValue] = None
    direct: Optional[ReplyModeValue] = None


@dataclass
class FeishuConfig:
    streaming: Optional[bool] = None
    replyMode: Optional[Union[ReplyModeValue, FeishuReplyModeConfig]] = None
    blockStreaming: Optional[bool] = None
    footer: Optional[FeishuFooterConfig] = None
    toolUseDisplay: Optional[FeishuToolUseDisplayConfig] = None
    verboseDefault: Optional[ToolUseMode] = None


@dataclass
class ReplyPayload:
    text: str = ""
    isReasoning: bool = False
    mediaUrl: Optional[str] = None
    mediaUrls: Optional[list[str]] = None
    interactive: bool = False
    btw: bool = False
    audioAsVoice: bool = False
    channelData: Optional[dict[str, object]] = None


@dataclass
class FeishuProbeResult:
    ok: bool
    error: Optional[str] = None
    appId: Optional[str] = None
    botName: Optional[str] = None
    botOpenId: Optional[str] = None


@dataclass
class CardCallbackOperator:
    open_id: Optional[str] = None
    user_id: Optional[str] = None


SILENT_REPLY_TOKEN = "NO_REPLY"
