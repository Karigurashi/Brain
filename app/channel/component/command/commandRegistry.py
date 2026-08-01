"""CommandRegistry —— 指令注册与分发。

维护 name/alias → Command 的映射表，解析含前缀的输入并异步分发到对应 handler。
支持任意单字符前缀（如 /、! 等），由构造函数 prefix 参数指定。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Dict, List

from .command import Command

if TYPE_CHECKING:
    from .commandContext import CommandContext


class CommandRegistry:
    """指令注册表 —— 注册、查询与异步分发。

    用法::

        registry = CommandRegistry(prefix="/")
        registry.Register(Command("help", "Show help", _HelpAsync))
        handled = await registry.DispatchAsync("/help", ctx)
    """

    def __init__(self, prefix: str = "/") -> None:
        self._prefix: str = prefix
        self._lookup: Dict[str, Command] = {}
        self._commands: List[Command] = []

    @property
    def Prefix(self) -> str:
        """指令前缀字符。"""
        return self._prefix

    # ---- 注册 ----

    def Register(self, command: Command) -> None:
        """注册一条指令及其别名。

        重复注册同名指令会替换旧映射。

        Args:
            command: Command 实例。
        """
        self._commands = [c for c in self._commands if c.name != command.name]
        self._commands.append(command)
        self._lookup[command.name] = command
        for alias in command.aliases:
            self._lookup[alias] = command

    # ---- 分发 ----

    async def DispatchAsync(self, userInput: str, ctx: CommandContext) -> bool:
        """解析并分发指令。

        输入格式: ``{prefix}command arg1 arg2``

        Args:
            userInput: 含前缀的完整输入。
            ctx: 命令处理上下文。

        Returns:
            是否成功匹配到指令。
        """
        stripped = userInput[len(self._prefix):]
        parts = stripped.split(None, 1)
        if not parts:
            ctx.PrintError(f"Empty command. Type {self._prefix}help for available commands.")
            return False

        name = parts[0].lower()
        args = parts[1] if len(parts) > 1 else ""

        command = self._lookup.get(name)
        if command is None:
            ctx.PrintError(
                f"Unknown command: {self._prefix}{name}. "
                f"Type {self._prefix}help for available commands."
            )
            return False

        await command.handler(ctx, args)
        return True

    # ---- 查询 ----

    def GetCommands(self) -> List[Command]:
        """返回去重后的命令列表。"""
        return list(self._commands)

    def GetHelpText(self) -> str:
        """生成格式化的帮助文本，命令按名称排序。

        Returns:
            每行一条命令的格式: ``  /name (alias1, alias2)  - description``
        """
        lines: List[str] = []
        seen: set[str] = set()
        for cmd in sorted(self._commands, key=lambda c: c.name):
            if cmd.name in seen:
                continue
            seen.add(cmd.name)
            line = f"  {self._prefix}{cmd.name}"
            aliases = ", ".join(f"{self._prefix}{a}" for a in cmd.aliases)
            if aliases:
                line += f" ({aliases})"
            line += f"  - {cmd.description}"
            lines.append(line)
        return "\n".join(lines)
