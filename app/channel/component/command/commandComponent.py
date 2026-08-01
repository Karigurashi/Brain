"""CommandComponent —— 指令系统组件，由 BaseChannel 装配挂载。

维护 CommandRegistry，负责指令注册与消息发送。
指令响应通过 channel.Platform.OnSendResponseAsync 投递到平台层。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from ...channelComponent import BaseChannelComponent
from ...channelMessage import ChannelMessage
from ..group import GroupContext
from .builtinCommands import RegisterBuiltinCommands
from .command import Command
from .commandContext import CommandContext
from .commandRegistry import CommandRegistry

if TYPE_CHECKING:
    from ...baseChannel import BaseChannel


class CommandComponent(BaseChannelComponent):
    """指令系统组件 —— 指令注册表与消息发送。

    由 BaseChannel.__init__ 装配挂载，通过 channel.GetComponent(CommandComponent) 访问。

    用法::

        channel = BaseChannel()
        commands = channel.GetComponent(CommandComponent)
        commands.RegisterCommand(Command("hello", "Say hello", _HelloAsync))
        await commands.SendMessageAsync(group, message)
    """

    def __init__(self) -> None:
        super().__init__()
        self._commandRegistry: CommandRegistry = CommandRegistry()

    # ---- BaseComponent 生命周期 ----

    def OnInitialize(self, channel: BaseChannel) -> None:
        super().OnInitialize(channel)
        self._commandRegistry = CommandRegistry(channel.Config.commandPrefix)
        RegisterBuiltinCommands(self._commandRegistry)

    def OnDestroy(self) -> None:
        pass

    # ---- 属性 ----

    @property
    def CommandRegistry(self) -> CommandRegistry:
        return self._commandRegistry

    # ---- 注册 ----

    def RegisterCommand(self, command: Command) -> None:
        self._commandRegistry.Register(command)

    # ---- 消息发送 ----

    async def SendMessageAsync(
        self,
        groupContext: GroupContext,
        message: ChannelMessage,
    ) -> None:
        """将指令消息发送到指令系统处理并投递响应。"""
        channel = self._channel  # type: ignore[assignment]
        platform = channel.Platform
        ctx = platform.CreateCommandContext(
            groupContext.groupId, message
        )
        await self._commandRegistry.DispatchAsync(message.content, ctx)

        if ctx.HasResponse:
            await platform.OnSendResponseAsync(
                groupContext.groupId,
                ctx.GetResponseText(),
            )