"""BasePlatformComponent —— 平台 SPI 组件基类，定义 Channel 平台 I/O 的全部扩展点。

每个平台适配器（CLI、飞书等）实现一个 BasePlatformComponent 子类，
通过 BaseChannel(platformType=...) 按具体类型挂载。组件间一律经
channel.Platform 访问平台 SPI，禁止 GetComponent(BasePlatformComponent)
（Entity 按具体类型键控，对基类取件会触发幻影实例自动生成）。

默认实现即"无操作平台"：全部钩子为空或记录警告，SendMessageAsync
默认非阻塞分发，同时作为 BaseChannel 的默认 platformType。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from common.cancellationToken import CancellationToken
from common.logger import Logger

from ...channelComponent import BaseChannelComponent
from ..command import CommandComponent, CommandContext

if TYPE_CHECKING:
    from agent import AgentStreamEvent
    from ...channelMessage import ChannelMessage
    from ..group import GroupContext


class BasePlatformComponent(BaseChannelComponent):
    """平台 SPI 组件基类 —— Channel 平台 I/O 扩展点集合（默认无操作实现）。

    子类按需 override:
        - OnStartAsync / OnStopAsync: 平台启动 / 停止逻辑。
        - OnAgentEventSync: Agent 流式事件处理。
        - OnSendResponseAsync: 指令响应投递。
        - OnGroupCreated / OnGroupRemoved: 群组回调。
        - CreateCommandContext: 平台特定指令上下文工厂。
        - SendMessageAsync: Agent 消息分发模式。
    """

    # ---- 生命周期钩子 ----

    async def OnStartAsync(
        self,
        cancellationToken: Optional[CancellationToken] = None,
    ) -> None:
        pass

    async def OnStopAsync(
        self,
        cancellationToken: Optional[CancellationToken] = None,
    ) -> None:
        pass

    # ---- 响应投递 ----

    async def OnSendResponseAsync(
        self,
        groupId: str,
        content: str,
        cancellationToken: Optional[CancellationToken] = None,
    ) -> None:
        Logger.Warning(
            f"BasePlatformComponent.OnSendResponseAsync not implemented: "
            f"groupId={groupId}, content_len={len(content)}"
        )

    # ---- Agent 事件 ----

    def OnAgentEventSync(
        self,
        groupId: str,
        event: AgentStreamEvent,
    ) -> None:
        pass

    # ---- 群组回调 ----

    def OnGroupCreated(self, groupId: str) -> None:
        pass

    def OnGroupRemoved(self, groupId: str) -> None:
        pass

    # ---- 指令上下文工厂 ----

    def CreateCommandContext(
        self,
        groupId: str,
        message: ChannelMessage,
    ) -> CommandContext:
        channel = self._channel  # type: ignore[assignment]
        return CommandContext(
            channel,
            groupId,
            message,
            channel.GetComponent(CommandComponent).CommandRegistry,
        )

    # ---- Agent 消息分发 ----

    async def SendMessageAsync(
        self,
        group: GroupContext,
        message: ChannelMessage,
    ) -> None:
        from ..group import GroupComponent
        channel = self._channel  # type: ignore[assignment]
        channel.GetComponent(GroupComponent).SendMessage(
            group.groupId, message
        )