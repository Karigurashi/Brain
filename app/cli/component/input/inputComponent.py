"""InputComponent —— CLI 输入组件，基于 prompt_toolkit 的终端行输入。

提供完整行编辑能力：光标移动、上下键命令历史（内存）、
Ctrl+A/E/U/K/W 编辑键位、bracketed paste 多行粘贴（不逐行提交）。

Ctrl+C 语义（保持原 CLI 习惯）：
- 当前行有内容 → 清空取消本次输入，重新等待。
- 当前行为空 → 请求退出（与原"空闲 Ctrl+C 退出"一致）。
Ctrl+D / EOF → 请求退出。

非 TTY 环境（管道输入 / 输出重定向）无控制台屏幕缓冲，prompt_toolkit
无法创建会话，ReadInputAsync 回退为 stdin 逐行读取（保持管道可用）。

与渲染层的协调性：CLI 阻塞模式保证 prompt 仅在 IDLE 出现，
Agent 流式输出期间不在 prompt 中，两者天然互斥，无需 patch_stdout。
"""

from __future__ import annotations

import asyncio
import sys
from typing import Optional

from prompt_toolkit import PromptSession
from prompt_toolkit.formatted_text import ANSI
from prompt_toolkit.history import InMemoryHistory
from prompt_toolkit.key_binding import KeyBindings, KeyPressEvent

from app.channel import BaseChannelComponent


class InputComponent(BaseChannelComponent):
    """CLI 输入组件 —— prompt_toolkit 会话封装。

    由 CliPlatformComponent.OnInitialize 编排触发，通过
    channel.GetComponent(InputComponent) 访问。
    """

    def __init__(self) -> None:
        super().__init__()
        self._session: Optional[PromptSession] = None
        self._promptText: str = ""

    def OnInitialize(self, entity) -> None:
        """override: 创建 prompt 会话（内存历史 + 自定义 Ctrl+C 键位）。

        非 TTY 环境（管道 / 重定向）跳过会话创建，
        ReadInputAsync 回退为 stdin 逐行读取。
        """
        super().OnInitialize(entity)
        cliConfig = self._channel.Config  # type: ignore[union-attr]
        self._promptText = cliConfig.Color(cliConfig.ICON_PROMPT, cliConfig.PURPLE) + " "
        if not (sys.stdin.isatty() and sys.stdout.isatty()):
            return

        keyBindings = KeyBindings()

        @keyBindings.add('c-c')
        def _OnCtrlC(event: KeyPressEvent) -> None:
            buffer = event.app.current_buffer
            if buffer.text:
                # 有内容：清空当前行（取消本次输入）
                buffer.reset()
            else:
                # 空行：冒泡 KeyboardInterrupt，由 ReadInputAsync 转为退出请求
                event.app.exit(exception=KeyboardInterrupt)

        self._session = PromptSession(
            history=InMemoryHistory(),
            key_bindings=keyBindings,
            enable_history_search=False,
        )

    async def ReadInputAsync(self) -> Optional[str]:
        """读取一行用户输入（阻塞至提交）。

        Returns:
            - None: 请求退出（空行 Ctrl+C / Ctrl+D / EOF）。
            - "": 空行（REPL 跳过本次循环）。
            - 其余: 有效输入文本（可能含多行粘贴内容）。
        """
        if self._session is None:
            return await self._ReadLineFallbackAsync()
        try:
            return await self._session.prompt_async(ANSI(self._promptText))
        except (KeyboardInterrupt, EOFError):
            return None

    async def _ReadLineFallbackAsync(self) -> Optional[str]:
        """非 TTY 回退：打印提示符后经 executor 读取 stdin 一行。

        Returns:
            - None: EOF（请求退出）。
            - 其余: 输入文本（已去除行尾换行，空行为空串）。
        """
        sys.stdout.write(self._promptText)
        sys.stdout.flush()
        line = await asyncio.get_running_loop().run_in_executor(
            None, sys.stdin.readline,
        )
        if not line:  # EOF
            return None
        return line.rstrip('\n\r')
