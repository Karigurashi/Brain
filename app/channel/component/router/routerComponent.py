"""RouterComponent —— 入站消息路由组件。

路由入站消息：内容以 commandPrefix 开头时走指令分发（CommandComponent），
否则委托平台组件（channel.Platform.SendMessageAsync）分发到 Agent。
"""

from __future__ import annotations

from ...channelComponent import BaseChannelComponent
from ...channelMessage import ChannelMessage
from ..command import CommandComponent
from ..group import GroupComponent


class RouterComponent(BaseChannelComponent):
    """入站消息路由组件 —— 指令 / Agent 分发决策。

    由 BaseChannel.__init__ 挂载，通过 channel.GetComponent(RouterComponent) 访问。

    用法::

        router = channel.GetComponent(RouterComponent)
        await router.SendMessageAsync(message)
    """

    async def SendMessageAsync(
        self,
        message: ChannelMessage,
    ) -> None:
        """路由入站消息：前缀匹配则分发指令，否则委托平台分发到 Agent。

        消息内容以 commandPrefix 开头时走指令分发流程（CommandComponent.SendMessageAsync），
        否则调用 channel.Platform.SendMessageAsync 分发到 Agent
        （默认非阻塞，CLI 平台 override 为阻塞模式）。
        """
        channel = self._channel  # type: ignore[assignment]
        group = channel.GetComponent(GroupComponent).EnsureGroup(
            message.groupId, message.groupName
        )

        content = message.content
        if content and content.startswith(channel.Config.commandPrefix):
            await channel.GetComponent(CommandComponent).SendMessageAsync(
                group, message
            )
        else:
            await channel.Platform.SendMessageAsync(
                group, message
            )
