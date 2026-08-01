"""Channel 指令定义 —— 名称、描述、处理函数与别名。

所有平台通用的指令数据载体，handler 接收 CommandContext。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Awaitable, Callable

if TYPE_CHECKING:
    from .commandContext import CommandContext


@dataclass
class Command:
    """指令定义 —— 名称、描述、异步处理函数与别名。

    Attributes:
        name: 指令名（不含前缀字符）。
        description: 简短描述，用于 /help 输出。
        handler: 异步处理函数，签名为 (CommandContext, str) -> None。
        aliases: 可选别名（不含前缀字符）。
    """

    name: str
    description: str
    handler: Callable[["CommandContext", str], Awaitable[None]]
    aliases: list[str] = field(default_factory=list)
