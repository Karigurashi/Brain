"""BaseChannel 框架 —— 多群消息路由纯外壳基类，统一 1 App → N 群 → 1 Agent/群 模式。

BaseChannel 不处理任何细节逻辑，仅装配组件：
生命周期（LifecycleComponent）、消息路由（RouterComponent）、群组管理
（GroupComponent）、指令系统（CommandComponent）、平台 SPI（BasePlatformComponent）。
各平台适配器实现 BasePlatformComponent 子类并经 platformType 注入即可接入 Agent 体系。

Usage::

    class FeishuPlatformComponent(BasePlatformComponent):
        async def OnSendResponseAsync(self, groupId, content, cancellationToken=None):
            await self._api.SendMessage(groupId, content)

        async def OnStartAsync(self, cancellationToken=None):
            await self._api.StartWebhook()

    channel = BaseChannel(
        ChannelConfig(modelName="deepseek-chat"),
        platformType=FeishuPlatformComponent,
    )
    await channel.GetComponent(LifecycleComponent).StartAsync()

    # Webhook 收到消息时
    msg = ChannelMessage(groupId="group_123", userId="user_456", content="你好")
    await channel.GetComponent(RouterComponent).ReceiveMessageAsync(msg)
"""

from .baseChannel import BaseChannel
from .channelComponent import BaseChannelComponent
from .channelConfig import ChannelConfig
from .channelMessage import ChannelMessage
from .component.command import (
    Command,
    CommandComponent,
    CommandContext,
    CommandRegistry,
    RegisterBuiltinCommands,
)
from .component.group import GroupComponent, GroupContext
from .component.lifecycle import LifecycleComponent
from .component.platform import BasePlatformComponent
from .component.router import RouterComponent
from .eChannelState import EChannelState

__all__ = [
    "BaseChannel",
    "BaseChannelComponent",
    "BasePlatformComponent",
    "ChannelConfig",
    "ChannelMessage",
    "Command",
    "CommandComponent",
    "CommandContext",
    "CommandRegistry",
    "EChannelState",
    "GroupComponent",
    "GroupContext",
    "LifecycleComponent",
    "RegisterBuiltinCommands",
    "RouterComponent",
]
