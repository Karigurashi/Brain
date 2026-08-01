"""FeishuAppConfig —— 飞书通道配置（ChannelConfig + 凭证）。

固定 WebSocket 长连接；卡片策略为 mango 定死实现。
"""

from __future__ import annotations

from dataclasses import dataclass

from app.channel.channelConfig import ChannelConfig
from app.feishu.core.types import (
    FeishuConfig,
    FeishuCredentials,
    FeishuFooterConfig,
    LarkBrand,
)


_MANGO_CARD_CONFIG = FeishuConfig(
    streaming=True,
    replyMode="streaming",
    footer=FeishuFooterConfig(
        status=False,
        elapsed=True,
        tokens=True,
        cache=True,
        model=False,
    ),
    verboseDefault="on",
)


@dataclass
class FeishuAppConfig(ChannelConfig):
    """飞书 App 配置。

    Attributes:
        appId / appSecret: 飞书应用凭证。
        brand: feishu / lark / 自定义 base URL。
    """

    appId: str = ""
    appSecret: str = ""
    brand: LarkBrand = "feishu"

    def ToCredentials(self) -> FeishuCredentials:
        return FeishuCredentials(
            appId=self.appId,
            appSecret=self.appSecret,
            brand=self.brand,
            accountId="default",
        )

    def ToCardConfig(self) -> FeishuConfig:
        return _MANGO_CARD_CONFIG
