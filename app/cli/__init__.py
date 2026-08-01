"""Agent CLI 终端模块 —— 对标 Claude Code 交互模式的 REPL 终端。

基于 BaseChannel 框架，CliApp 作为纯装配壳，CliPlatformComponent 编排
component/ 下的领域组件（Console / Render / Input / Repl / CliContext）：
单群模式（groupId="cli"），斜杠指令 + 普通消息 + Ctrl+C 取消。

Usage::

    from app.cli import CliApp, CliConfig
    from app.channel import LifecycleComponent
    app = CliApp()  # 从 settings.json channel.cli 解析
    app.GetComponent(LifecycleComponent).Start()
"""


from ..channel import Command, CommandRegistry
from .cliApp import CliApp
from .cliConfig import CliConfig
from .component.command import CliContext
from .component.render import CliRenderer

__all__ = [
    "CliApp",
    "CliContext",
    "CliConfig",
    "CliRenderer",
    "Command",
    "CommandRegistry",
]
