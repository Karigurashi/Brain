"""FeishuApp —— 飞书 Channel 入口，继承 BaseChannel 的纯装配壳。

走 mango channel 模块（Lifecycle / Router / Group / Command）+ AgentSdk，
平台行为由 FeishuPlatformComponent / CardComponent 承担。

config 为 None 时从 ``settings.json`` 的 ``channel.feishu`` 解析 FeishuAppConfig。

Usage::

    app = FeishuApp()  # Settings.Get("channel.feishu", FeishuAppConfig)
    app.GetComponent(LifecycleComponent).Start()
"""

from __future__ import annotations

from typing import Optional

from app.channel import BaseChannel
from app.feishu.component.card import CardComponent
from app.feishu.component.platform import FeishuPlatformComponent
from app.feishu.feishuConfig import FeishuAppConfig
from setting import Settings


class FeishuApp(BaseChannel):
    """飞书 Channel —— 装配平台 SPI 与卡片组件。"""

    def __init__(self, config: Optional[FeishuAppConfig] = None) -> None:
        super().__init__(config or Settings.Get("channel.feishu", FeishuAppConfig))

    def SetupComponents(self) -> None:
        super().SetupComponents()
        self.AddComponent(CardComponent)
        self._platformComponent = self.AddComponent(FeishuPlatformComponent)
