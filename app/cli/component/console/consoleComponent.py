"""ConsoleComponent —— Windows 终端模式初始化组件。

负责控制台输出 / 输入模式配置：
- UTF-8 编码（代码页 65001 + Python I/O 包装器重配置）。
- ANSI 转义序列支持（ENABLE_VIRTUAL_TERMINAL_PROCESSING）。
- QuickEdit 输入模式（ENABLE_QUICK_EDIT_MODE），启用鼠标选择复制与右键粘贴。
"""

from __future__ import annotations

import sys

from app.channel import BaseChannelComponent


class ConsoleComponent(BaseChannelComponent):
    """终端模式组件 —— 控制台编码 / ANSI / QuickEdit 初始化。

    由 CliPlatformComponent.OnInitialize 编排触发，通过
    channel.GetComponent(ConsoleComponent) 访问。
    """

    def OnInitialize(self, entity) -> None:
        """override: 初始化终端输出与输入模式（幂等，进程级一次性配置）。"""
        super().OnInitialize(entity)
        self._EnsureUtf8Stdout()
        self._EnableQuickEditMode()

    # ---- 输出模式 ----

    @staticmethod
    def _EnsureUtf8Stdout() -> None:
        """确保 stdout 使用 UTF-8 编码，并启用 ANSI 转义序列（Windows CMD 兼容）。

        Windows CMD 默认不支持 ANSI 颜色码和 UTF-8，需要：
        1. 启用虚拟终端处理（Virtual Terminal Processing）以支持 ANSI 转义序列。
        2. 将控制台代码页设为 UTF-8 (65001)。
        3. 将 Python stdout 包装器编码设为 utf-8。
        """
        if sys.platform != "win32":
            try:
                sys.stdout.reconfigure(encoding='utf-8')
            except (AttributeError, OSError):
                pass
            return

        import ctypes

        # ---- 启用虚拟终端处理（ANSI 转义序列支持） ----
        # 参考微软官方文档：
        # https://learn.microsoft.com/windows/console/setconsolemode
        kernel32 = ctypes.windll.kernel32

        ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004
        STD_OUTPUT_HANDLE = -11

        stdoutHandle = kernel32.GetStdHandle(STD_OUTPUT_HANDLE)
        if stdoutHandle and stdoutHandle != -1:
            # 获取当前控制台模式
            originalMode = ctypes.c_ulong()
            if kernel32.GetConsoleMode(stdoutHandle, ctypes.byref(originalMode)):
                newMode = originalMode.value | ENABLE_VIRTUAL_TERMINAL_PROCESSING
                kernel32.SetConsoleMode(stdoutHandle, newMode)

        # ---- 设置控制台代码页为 UTF-8 ----
        # chcp 65001 等效操作
        # 参考：https://learn.microsoft.com/windows/win32/api/consoleapi/nf-consoleapi-setconsoleoutputcp
        CP_UTF8 = 65001
        kernel32.SetConsoleOutputCP(CP_UTF8)
        kernel32.SetConsoleCP(CP_UTF8)

        # ---- 重配置 Python I/O 包装器 ----
        for stream in (sys.stdout, sys.stderr, sys.stdin):
            try:
                stream.reconfigure(encoding='utf-8')
            except (AttributeError, OSError):
                pass

    # ---- 输入模式 ----

    @staticmethod
    def _EnableQuickEditMode() -> None:
        """启用 Windows 控制台 QuickEdit 输入模式（鼠标选择复制 / 右键粘贴）。

        QuickEdit 模式下用户可直接用鼠标拖选终端文本（Enter 或右键复制），
        右键单击粘贴剪贴板内容。必须搭配 ENABLE_EXTENDED_FLAGS 一同设置。
        参考：https://learn.microsoft.com/windows/console/setconsolemode
        """
        if sys.platform != "win32":
            return

        import ctypes

        kernel32 = ctypes.windll.kernel32

        ENABLE_QUICK_EDIT_MODE = 0x0040
        ENABLE_EXTENDED_FLAGS = 0x0080
        STD_INPUT_HANDLE = -10

        stdinHandle = kernel32.GetStdHandle(STD_INPUT_HANDLE)
        if not stdinHandle or stdinHandle == -1:
            return

        originalMode = ctypes.c_ulong()
        if kernel32.GetConsoleMode(stdinHandle, ctypes.byref(originalMode)):
            newMode = originalMode.value | ENABLE_QUICK_EDIT_MODE | ENABLE_EXTENDED_FLAGS
            kernel32.SetConsoleMode(stdinHandle, newMode)
