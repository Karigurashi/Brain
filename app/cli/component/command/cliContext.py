"""CliContext —— CLI 平台指令上下文，继承 CommandContext。

override Print/PrintDim 等方法实现即时终端输出（不缓冲），
其余组件访问、退出控制等均继承自 CommandContext。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.channel import CommandContext

from ...cliConfig import CliConfig
from ..render import CliRenderer

if TYPE_CHECKING:
    from app.channel import BaseChannel, ChannelMessage, CommandRegistry


class CliContext(CommandContext):
    """CLI 平台指令上下文 —— 终端即时输出。

    与基类 CommandContext 的区别：
    - Print/PrintDim/PrintWarning/PrintError 直接写入终端（通过 CliRenderer），
      不累积到响应缓冲区，因此 HasResponse 始终为 False，
      CommandComponent.DispatchAsync 不会调用 Platform.OnSendResponseAsync。
    - 额外提供 Config 属性访问 CliConfig（ANSI 主题、FormatK 等）。
    """

    def __init__(
        self,
        channel: BaseChannel,
        groupId: str,
        message: ChannelMessage,
        registry: CommandRegistry,
        cliConfig: CliConfig,
        renderer: CliRenderer,
    ) -> None:
        super().__init__(channel, groupId, message, registry)
        self._cliConfig: CliConfig = cliConfig
        self._renderer: CliRenderer = renderer

    # ---- CLI 配置 ----

    @property
    def Config(self) -> CliConfig:
        """CLI 终端渲染配置。"""
        return self._cliConfig

    # ---- 输出（override 基类，直接写终端，不缓冲） ----

    def Print(self, text: str) -> None:
        self._renderer.PrintInfo(text)

    def PrintDim(self, text: str) -> None:
        self._renderer.PrintDim(text)

    def PrintWarning(self, text: str) -> None:
        self._renderer.PrintWarning(text)

    def PrintError(self, text: str) -> None:
        self._renderer.PrintError(text)