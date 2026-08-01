"""Markdown 样式优化。"""

from __future__ import annotations

import re

IMAGE_RE = re.compile(r"!\[([^\]]*)\]\(([^)\s]+)\)")


def CompactMarkdownBlankLines(text: str) -> str:
    """去掉多余空行：空白行压成单换行，保留内容行本身。"""
    if not text:
        return text
    result = text.replace("\r\n", "\n").replace("\r", "\n")
    # 去掉行尾空白，避免「看起来空、实际有空格」的伪空行
    result = re.sub(r"[ \t]+\n", "\n", result)
    result = re.sub(r"\n[ \t]+(?=\n)", "\n", result)
    # 连续空行 / 多换行 → 单换行
    result = re.sub(r"\n{2,}", "\n", result)
    return result.strip()


def OptimizeMarkdownStyle(text: str, cardVersion: int = 2) -> str:
    try:
        result = _OptimizeMarkdownStyle(text, cardVersion)
        return _StripInvalidImageKeys(result)
    except Exception:
        return CompactMarkdownBlankLines(text) if text else text


def _OptimizeMarkdownStyle(text: str, cardVersion: int = 2) -> str:
    """优化 Markdown 排版：标题降级 + 表格/标题/代码块 <br> 段落间距。

    对齐 openclaw-lark-main src/card/markdown-style.ts。

    关键设计：
    - 代码块先抽出占位保护，处理完再还原
    - 表格/标题/代码块通过 <br> 产生飞书卡片内的段落间距
    - 最终仅压缩 3+ 连续空行 → 2（保留 \n\n 段落分隔），
      既解决 LLM 输出的多余空行，又不会破坏表格排版
    """
    mark = "___CB_"
    codeBlocks: list[str] = []

    def _ReplaceCodeBlock(match: re.Match[str]) -> str:
        prefix = match.group(1) or ""
        block = match.group(0)[len(prefix) :]
        codeBlocks.append(block)
        return f"{prefix}{mark}{len(codeBlocks) - 1}___"

    # 1. 抽出代码块，用占位符保护，处理后再还原
    result = re.sub(r"(^|\n)(`{3,})([^\n]*)\n[\s\S]*?\n\2(?=\n|$)", _ReplaceCodeBlock, text)

    # 2. 标题降级：仅当原文档包含 h1~h3 标题时执行
    #    先 H2~H6 → H5，再 H1 → H4（顺序不能颠倒，否则 H1→H4 后会被 H2~H6 规则再次匹配成 H5）
    if re.search(r"^#{1,3} ", text, re.MULTILINE):
        result = re.sub(r"^#{2,6} (.+)$", r"##### \1", result, flags=re.MULTILINE)
        result = re.sub(r"^# (.+)$", r"#### \1", result, flags=re.MULTILINE)

    if cardVersion >= 2:
        # 3. 连续标题间插入 <br> 产生段落间距
        result = re.sub(r"^(#{4,5} .+)\n{1,2}(#{4,5} )", r"\1\n<br>\n\2", result, flags=re.MULTILINE)
    
        # 4. 表格排版优化（对齐 TS 4a~4e）
        # 4a. 非表格行直接跟表格行时，补一个空行
        result = re.sub(r"^([^|\n].*)\n(\|.+\|)", r"\1\n\n\2", result, flags=re.MULTILINE)
        # 4b. 表格前插入 <br>（在空行之前）
        result = re.sub(r"\n\n((?:\|.+\|[^\S\n]*\n?)+)", r"\n\n<br>\n\n\1", result)
        # 4c. 表格后追加 <br>（跳过分隔线/标题/加粗/文末）
        def _TableAfterBr(match: re.Match[str]) -> str:
            m = match.group(0)
            after = result[match.end():].lstrip("\n")
            if not after or re.match(r"^(---|#{4,5} |\*\*)", after):
                return m
            return m + "\n<br>\n"
    
        result = re.sub(r"((?:^\|.+\|[^\S\n]*\n?)+)", _TableAfterBr, result, flags=re.MULTILINE)
        # 4d. 表格前是普通文本（非标题、非加粗行）时简化间距
        result = re.sub(
            r"^((?!#{4,5} )(?!\*\*).+)\n\n(<br>)\n\n(\|)", r"\1\n\2\n\3", result, flags=re.MULTILINE
        )
        # 4d2. 表格前是加粗行时，<br> 紧贴加粗行，空行保留在后面
        result = re.sub(r"^(\*\*.+)\n\n(<br>)\n\n(\|)", r"\1\n\2\n\n\3", result, flags=re.MULTILINE)
        # 4e. 表格后是普通文本（非标题、非加粗行）时简化间距
        result = re.sub(r"(\|[^\n]*\n)\n(<br>\n)((?!#{4,5} )(?!\*\*))", r"\1\2\3", result, flags=re.MULTILINE)
    
        # 5. 还原代码块，包裹 <br> 产生段落间距（对齐 TS：先还原再压缩）
        for index, block in enumerate(codeBlocks):
            result = result.replace(f"{mark}{index}___", f"\n<br>\n{block}\n<br>\n")
    
        # 6. 最终压缩（对齐 TS：还原代码块后再压缩多余空行）
        result = re.sub(r"\n{3,}", "\n\n", result)
    else:
        for index, block in enumerate(codeBlocks):
            result = result.replace(f"{mark}{index}___", f"\n{block}\n")
    
    return result


def _StripInvalidImageKeys(text: str) -> str:
    if "![" not in text:
        return text

    def _Replace(match: re.Match[str]) -> str:
        value = match.group(2)
        if value.startswith("img_"):
            return match.group(0)
        return ""

    return IMAGE_RE.sub(_Replace, text)
