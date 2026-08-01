"""BaseChannel —— 多群消息路由框架纯外壳基类。

BaseChannel 不处理任何细节逻辑，仅持有 ChannelConfig 数据并完成组件装配，
全部职责由组件承担::

    - LifecycleComponent:    运行状态机与启停编排（Start / StopAsync / RequestStop）。
    - RouterComponent:       入站消息路由（指令前缀匹配 / Agent 分发）。
    - GroupComponent:        群组管理与 Agent 创建。
    - CommandComponent:      指令注册与分发。
    - BasePlatformComponent: 平台 SPI（各平台子类实现，经 channel.Platform 访问）。

架构概览::

    ┌────────────────────────────────────────────────┐
    │            BaseChannel（纯装配外壳）             │
    │  Config / Platform                              │
    │  ┌────────────┐ ┌──────────┐ ┌───────────────┐ │
    │  │ Lifecycle  │ │ Router   │ │ Group         │ │
    │  │ 状态机启停  │ │ 消息路由  │ │ 群组 / Agent   │ │
    │  └────────────┘ └──────────┘ └───────────────┘ │
    │  ┌────────────┐ ┌───────────────────────────┐  │
    │  │ Command    │ │ Platform SPI（平台子类）    │  │
    │  │ 指令系统    │ │ 启动 / 事件 / 投递 / 分发   │  │
    │  └────────────┘ └───────────────────────────┘  │
    └────────────────────────────────────────────────┘

入站消息流:
  普通消息:  Platform → ChannelMessage → RouterComponent.ReceiveMessageAsync
             → GroupComponent.EnsureGroup → Platform.SendMessageAsync
             → AgentSdk.SendMessage（非阻塞 fire-and-forget）
             → Agent.RunAsync(stream=True) → EventBus 事件
             → GroupComponent._OnEvent → Platform.OnAgentEventSync

  指令消息:  Platform → RouterComponent.ReceiveMessageAsync
             → content.startswith(prefix) → CommandComponent.DispatchAsync
             → Command.handler(ctx, args) → Platform.OnSendResponseAsync 投递

Usage::

    class FeishuPlatformComponent(BasePlatformComponent):
        async def OnStartAsync(self, cancellationToken=None):
            await self._api.StartWebhook()

    class FeishuChannel(BaseChannel):
        def SetupComponents(self) -> None:
            super().SetupComponents()
            self._platformComponent = self.AddComponent(FeishuPlatformComponent)

    channel = FeishuChannel(ChannelConfig(modelName="deepseek-chat"))
    await channel.GetComponent(LifecycleComponent).StartAsync()

    msg = ChannelMessage(groupId="group_123", userId="user_456", content="你好")
    await channel.GetComponent(RouterComponent).ReceiveMessageAsync(msg)
"""

from __future__ import annotations

from typing import Optional

from agent.sdk import AgentSdk
from common.entity.entity import Entity

from .channelConfig import ChannelConfig
from .component.command import CommandComponent
from .component.group import GroupComponent
from .component.lifecycle import LifecycleComponent
from .component.platform import BasePlatformComponent
from .component.router import RouterComponent


class BaseChannel(Entity):
    """多群消息路由框架纯外壳基类 —— 仅装配内置组件，不含任何细节逻辑。

    子类（平台适配器）在 __init__ 中装配平台 SPI 组件并赋值
    self._platformComponent，实现平台接入。
    自身不允许 override 任何业务方法（无业务方法可 override）。

    Args:
        config: Channel 创建配置，None 时使用默认 ChannelConfig。
    """

    def __init__(
        self,
        config: Optional[ChannelConfig] = None,
    ) -> None:
        super().__init__()
        self._config: ChannelConfig = config or ChannelConfig()
        self._platformComponent: Optional[BasePlatformComponent] = None
        self._sdk: AgentSdk[str] = AgentSdk[str](
            modelName=self._config.modelName,
            agentConfig=self._config.agentConfig,
            maxConcurrent=self._config.maxConcurrentGroups,
        )

        # ---- 内置组件装配 ----
        self.SetupComponents()

    def SetupComponents(self) -> None:
        """装配内置组件与平台 SPI 组件。子类必须重写并以 super().SetupComponents() 开头。"""
        self.AddComponent(LifecycleComponent)
        self.AddComponent(RouterComponent)
        self.AddComponent(GroupComponent)
        self.AddComponent(CommandComponent)

    # ---- 数据属性 ----

    @property
    def Config(self) -> ChannelConfig:
        """Channel 创建配置（只读数据）。"""
        return self._config

    @property
    def Sdk(self) -> AgentSdk[str]:
        """AgentSdk 实例，Channel 级唯一入口。"""
        return self._sdk

    @property
    def Platform(self) -> BasePlatformComponent:
        """平台 SPI 组件（唯一访问路径，禁止 GetComponent(BasePlatformComponent)）。"""
        return self._platformComponent
