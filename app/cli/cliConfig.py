"""CliConfig —— CLI 终端 ANSI 主题、图标、边框与显示配置。

继承 ChannelConfig，在其基础上扩展 CLI 渲染相关的颜色、图标、
显示阈值及 Markdown→ANSI 渲染能力。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ..channel.channelConfig import ChannelConfig


@dataclass
class CliConfig(ChannelConfig):
    """CLI 终端渲染配置 —— ANSI 颜色、图标、显示阈值。

    所有 ANSI 常量作为实例字段存储，方便子类定制主题。
    256 色码在多数现代终端（Windows Terminal / iTerm2 / Konsole）中可用，
    不支持时自动降级为标准 16 色。
    """

    # ---- 标准 16 色 (降级兜底) ----
    RESET: str = "\033[0m"
    BOLD: str = "\033[1m"
    DIM: str = "\033[2m"
    ITALIC: str = "\033[3m"

    RED: str = "\033[31m"
    GREEN: str = "\033[32m"
    YELLOW: str = "\033[33m"
    MAGENTA: str = "\033[35m"
    CYAN: str = "\033[36m"
    GRAY: str = "\033[90m"
    WHITE: str = "\033[97m"

    # ---- 256 色增强 (主流终端可用) ----
    PURPLE: str = "\033[38;5;141m"
    PURPLE_BRIGHT: str = "\033[38;5;183m"
    CYAN_BRIGHT: str = "\033[38;5;51m"
    AMBER: str = "\033[38;5;214m"

    # ---- Mango 渐变色谱 (绿 → 黄 → 橙) ----
    MANGO_GREEN: str = "\033[38;5;34m"
    MANGO_LIME: str = "\033[38;5;46m"
    MANGO_GOLD: str = "\033[38;5;220m"
    MANGO_ORANGE: str = "\033[38;5;208m"
    DEEP_ORANGE: str = "\033[38;5;202m"

    # ---- 背景色 ----
    BG_PURPLE: str = "\033[48;5;141m"
    BG_RESET: str = "\033[49m"

    # ---- 图标 ----
    ICON_THINKING: str = "\u25cf"
    ICON_TOOL: str = "\u25c6"
    ICON_ERROR: str = "\u2716"
    ICON_COMPACTION: str = "\u21bb"
    ICON_PROMPT: str = "\u276f"
    ICON_INFO: str = "\u2726"

    # ---- 框线字符 ----
    BOX_H: str = "\u2500"
    BOX_V: str = "\u2502"
    BOX_TL: str = "\u256d"
    BOX_TR: str = "\u256e"
    BOX_BL: str = "\u2570"
    BOX_BR: str = "\u256f"

    # ---- 显示限制 ----
    maxToolResultLines: int = 20
    maxToolResultChars: int = 200
    maxToolArgsDisplay: int = 200
    showThinking: bool = True
    showTokenUsage: bool = True

    # ---- 预编译正则（类属性，所有实例共享，避免 RenderMdLine 热路径重复编译） ----
    _RE_CODE_FENCE = re.compile(r'^```')
    _RE_HR = re.compile(r'^[-\*_]{3,}\s*$')
    _RE_HEADING = re.compile(r'^(#{1,4})\s+(.+)$')
    _RE_BLOCKQUOTE = re.compile(r'^>\s?(.*)$')
    _RE_UL = re.compile(r'^(\s*)[-\*]\s+(.+)$')
    _RE_OL = re.compile(r'^(\s*)(\d+)\.\s+(.+)$')
    _RE_BOLD = re.compile(r'\*\*(.+?)\*\*')
    _RE_CODE_SPAN = re.compile(r'`([^`]+)`')
    _RE_ITALIC = re.compile(r'(?<!\*)\*(\S(?:.*?\S)?)\*(?!\*)')
    _RE_ANSI = re.compile(r'\x1b\[[0-9;]*m')
    # 预计算常量
    _HR_LINE: str = "\u2500" * 50

    # ---- Mango 主题 Banner ----
    _MANGO_ART: tuple = (
        "        ,d8888b,        ",
        "       d8P'  `Y8b       ",
        "       88      88       ",
        "       88      88       ",
        "       Y8b,   ,d8P      ",
        "        `Y88888P'        ",
    )
    _MANGO_TEXT: tuple = (
        "\u2588\u2580\u2584\u2580\u2588 \u2584\u2580\u2588 \u2588\u2584\u2591\u2588 \u2588\u2580\u2580 \u2588\u2580\u2588",
        "\u2588\u2591\u2580\u2591\u2588 \u2588\u2580\u2588 \u2588\u2591\u2580\u2588 \u2588\u2584\u2588 \u2588\u2584\u2588",
    )
    _AGENT_TEXT: tuple = (
        "\u2584\u2580\u2588 \u2588\u2580\u2580 \u2588\u2580\u2580 \u2588\u2584\u2591\u2588 \u2580\u2588\u2580",
        "\u2588\u2580\u2588 \u2588\u2584\u2588 \u2588\u2588\u2584 \u2588\u2591\u2580\u2588 \u2591\u2588\u2591",
    )
    BANNER_SUBTITLE: str = "Mango Agent  \u00b7  Think  \u00b7  Act  \u00b7  Observe"

    # ---- 辅助方法 ----

    def Color(self, text: str, color: str) -> str:
        return f"{color}{text}{self.RESET}"

    def Dim(self, text: str) -> str:
        return f"{self.DIM}{text}{self.RESET}"

    def Bold(self, text: str) -> str:
        return f"{self.BOLD}{text}{self.RESET}"

    def Purple(self, text: str) -> str:
        return f"{self.PURPLE}{text}{self.RESET}"

    def CyanBright(self, text: str) -> str:
        return f"{self.CYAN_BRIGHT}{text}{self.RESET}"

    @staticmethod
    def FormatK(value: int) -> str:
        """将 token 数格式化为 k 单位。"""
        return f"{value / 1000.0:.1f}k"

    def Chip(self, text: str) -> str:
        return f"{self.BG_PURPLE}{self.WHITE} {text} {self.BG_RESET}{self.RESET}"

    def Separator(self, label: str = "") -> str:
        width = 60
        if label:
            side = (width - len(label) - 2) // 2
            left = self.BOX_H * side
            right = self.BOX_H * (width - len(label) - 2 - side)
            return self.Dim(f"{left} {self.Purple(label)}{self.Dim(right)}")
        return self.Dim(self.BOX_H * width)

    def TruncateLines(self, text: str, maxLines: int) -> str:
        lines = text.split('\n')
        if len(lines) <= maxLines:
            return text
        truncated = '\n'.join(lines[:maxLines])
        more = len(lines) - maxLines
        return f"{truncated}\n{self.Dim(f'... ({more} more lines)')}"

    # ---- Markdown → ANSI ----

    def RenderMdLine(self, line: str, inCodeBlock: bool) -> tuple[str, bool]:
        """将单行 Markdown 文本转换为 ANSI 格式化文本。"""
        s = line
        c = self

        # 代码块切换
        if c._RE_CODE_FENCE.match(s):
            if inCodeBlock:
                return (c.Dim(f"{c.BOX_V} ── end code-block"), False)
            else:
                lang = s[3:].strip()
                tag = f" {lang}" if lang else ""
                return (c.Dim(f"{c.BOX_V} ── code-block{tag} ───"), True)

        if inCodeBlock:
            return (c.Dim(f"{c.BOX_V} {s}"), True)

        # 空行
        if not s.strip():
            return ("", False)

        # 水平线
        if c._RE_HR.match(s):
            return (c.Dim(c._HR_LINE), False)

        # 标题：处理行内 **bold** 后再着色
        hm = c._RE_HEADING.match(s)
        if hm:
            level = len(hm.group(1))
            text = c._RenderMdInline(hm.group(2))
            if level == 1:
                return (f"{c.Bold(c.Color(text, c.PURPLE_BRIGHT))}", False)
            elif level == 2:
                return (f"{c.Bold(c.Color(text, c.PURPLE))}", False)
            else:
                return (f"{c.Bold(text)}", False)

        # 引用块
        bq = c._RE_BLOCKQUOTE.match(s)
        if bq:
            return (f"{c.Dim(f'{c.BOX_V} {c._RenderMdInline(bq.group(1))}')}", False)

        # 无序列表
        ul = c._RE_UL.match(s)
        if ul:
            indent = ul.group(1)
            text = c._RenderMdInline(ul.group(2))
            return (f"{indent}{c.Purple('•')} {text}", False)

        # 有序列表
        ol = c._RE_OL.match(s)
        if ol:
            indent = ol.group(1)
            num = ol.group(2)
            text = c._RenderMdInline(ol.group(3))
            return (f"{indent}{c.Dim(f'{num}.')} {text}", False)

        # 行内格式化
        return (c._RenderMdInline(s), False)

    # 预计算行内替换模板（re.sub 字符串模式零函数调用，C 层执行）
    _REPL_BOLD: str = "\033[1m\\1\033[0m"
    _REPL_DIM: str = "\033[2m\\1\033[0m"

    def _RenderMdInline(self, text: str) -> str:
        """处理行内格式：**bold**, *italic*, `code`。

        使用 re.sub 的字符串替换模式（反向引用），避免每次调用创建 lambda 对象。
        """
        s = text
        s = self._RE_BOLD.sub(self._REPL_BOLD, s)
        s = self._RE_CODE_SPAN.sub(self._REPL_DIM, s)
        s = self._RE_ITALIC.sub(self._REPL_DIM, s)
        return s

    def RenderBanner(self, modelName: str, groupName: str) -> str:
        """渲染 Mango 主题 Banner，芒果图案应用绿→橙垂直渐变。"""
        lines: list[str] = []
        w = 62
        V = self.BOX_V

        def _stripAnsi(s: str) -> str:
            return self._RE_ANSI.sub('', s)

        def _box(s: str) -> str:
            visual = _stripAnsi(s)
            pad = (w - 4) - len(visual)
            if pad > 0:
                s = s + ' ' * pad
            return f"{self.Purple(V)} {s} {self.Purple(V)}"

        def _empty() -> str:
            return _box("")

        mangoColors = (
            self.MANGO_GREEN, self.MANGO_LIME, self.YELLOW,
            self.MANGO_GOLD, self.AMBER, self.MANGO_ORANGE,
        )
        art = self._MANGO_ART
        mangoText = self._MANGO_TEXT
        agentText = self._AGENT_TEXT

        lines.append(self.Purple(f"{self.BOX_TL}{self.BOX_H * (w - 2)}{self.BOX_TR}"))
        lines.append(_empty())
        # Row 0: 芒果顶行 + MANGO 第一行
        lines.append(_box(
            f"  {mangoColors[0]}{art[0]}{self.RESET}"
            f"    {self.MANGO_GOLD}{mangoText[0]}{self.RESET}"
        ))
        # Row 1: 芒果第二行 + MANGO 第二行
        lines.append(_box(
            f"  {mangoColors[1]}{art[1]}{self.RESET}"
            f"    {self.MANGO_GOLD}{mangoText[1]}{self.RESET}"
        ))
        # Row 2: 芒果第三行 + AGENT 第一行
        lines.append(_box(
            f"  {mangoColors[2]}{art[2]}{self.RESET}"
            f"      {self.PURPLE}{agentText[0]}{self.RESET}"
        ))
        # Row 3: 芒果第四行 + AGENT 第二行
        lines.append(_box(
            f"  {mangoColors[3]}{art[3]}{self.RESET}"
            f"      {self.PURPLE}{agentText[1]}{self.RESET}"
        ))
        # Row 4: 芒果第五行 (渐变底)
        lines.append(_box(f"  {mangoColors[4]}{art[4]}{self.RESET}"))
        # Row 5: 芒果第六行 (渐变底)
        lines.append(_box(f"  {mangoColors[5]}{art[5]}{self.RESET}"))

        lines.append(_empty())
        subtitle = self.BANNER_SUBTITLE
        pad = (w - 4 - len(subtitle)) // 2
        lines.append(
            f"{self.Purple(V)} {' ' * pad}{self.CyanBright(subtitle)}{' ' * (w - 4 - pad - len(subtitle))} {self.Purple(V)}"
        )
        lines.append(_empty())
        infoLine = f"  Model: {modelName}    Group: {groupName}"
        lines.append(_box(self.Dim(infoLine)))
        hintLine = "  /help commands  |  /exit quit  |  Ctrl+C interrupt"
        lines.append(_box(self.Dim(hintLine)))
        lines.append(_empty())
        lines.append(self.Purple(f"{self.BOX_BL}{self.BOX_H * (w - 2)}{self.BOX_BR}"))
        return '\n'.join(lines)
