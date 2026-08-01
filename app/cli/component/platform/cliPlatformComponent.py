"""CliPlatformComponent —— CLI 平台组件，SPI 实现层。

实现 BasePlatformComponent SPI，全部终端行为委托给 channel 上的领域组件：
- OnStartAsync → ReplComponent.RunAsync（REPL 主循环）。
- SendMessageAsync: 阻塞模式（用户等待响应）。
- OnAgentEventSync → RenderComponent.OnAgentEvent（事件实时渲染）。
- CreateCommandContext: 构造 CliContext（renderer 取自 RenderComponent）。
- OnSendResponseAsync: 空实现（CLI 指令经 CliContext.Print* 直接输出）。
"""

from __future__ import annotations

from typing import Optional

from agent import AgentStreamEvent
from common.cancellationToken import CancellationToken

from ....channel import (
    BasePlatformComponent,
    ChannelMessage,
    CommandComponent,
    GroupComponent,
    GroupContext,
)
from ..command import CliContext
from ..render import RenderComponent
from ..repl import ReplComponent


class CliPlatformComponent(BasePlatformComponent):
    """CLI 平台组件 —— SPI 实现层（不负责组件编排，由 CliApp 承担）。

    Usage::

        app = CliApp(CliConfig(modelName="deepseek-high"))
        app.GetComponent(LifecycleComponent).Start()
    """

    # ---- 平台 SPI ----

    async def OnStartAsync(
        self,
        cancellationToken: Optional[CancellationToken] = None,
    ) -> None:
        channel = self._channel  # type: ignore[assignment]
        await channel.GetComponent(ReplComponent).RunAsync(cancellationToken)

    async def SendMessageAsync(
        self,
        group: GroupContext,
        message: ChannelMessage,
    ) -> None:
        channel = self._channel  # type: ignore[assignment]
        await channel.GetComponent(GroupComponent).SendMessageAsync(
            group.groupId, message
        )

    def OnAgentEventSync(self, groupId: str, event: AgentStreamEvent) -> None:
        channel = self._channel  # type: ignore[assignment]
        channel.GetComponent(RenderComponent).OnAgentEvent(event)

    def CreateCommandContext(
        self,
        groupId: str,
        message: ChannelMessage,
    ) -> CliContext:
        channel = self._channel  # type: ignore[assignment]
        return CliContext(
            channel=channel,
            groupId=groupId,
            message=message,
            registry=channel.GetComponent(CommandComponent).CommandRegistry,
            cliConfig=self._channel.Config,  # type: ignore[union-attr]
            renderer=channel.GetComponent(RenderComponent).Renderer,
        )

    async def OnSendResponseAsync(
        self,
        groupId: str,
        content: str,
        cancellationToken: Optional[CancellationToken] = None,
    ) -> None:
        pass