"""正文清洗器 —— 使用 trafilatura 从 HTML 提取干净正文。"""

from __future__ import annotations

import re


class ContentCleaner:
    """从网页原始代码中提取干净纯文本。

    HTML 输入使用 trafilatura 自动剥离 script/style/广告/导航/页脚等杂质，
    纯文本输入做空白规范化后直接返回。
    """

    @staticmethod
    def Clean(text: str, isHtml: bool = False) -> str:
        """清洗输入文本，返回干净正文。

        Args:
            text: 原始文本或 HTML 代码。
            isHtml: 是否为 HTML 内容。若为 True 则使用 trafilatura 提取正文。

        Returns:
            清洗后的纯文本。
        """
        if not text or not text.strip():
            return ""

        if isHtml:
            return ContentCleaner._CleanHtml(text)

        return ContentCleaner._NormalizeWhitespace(text)

    @staticmethod
    def _CleanHtml(html: str) -> str:
        """使用 trafilatura 提取 HTML 正文，失败时回退到正则清洗。"""
        try:
            import trafilatura
            extracted = trafilatura.extract(
                html,
                include_comments=False,
                include_tables=True,
                include_images=False,
                include_links=False,
                include_formatting=False,
                output_format="txt",
            )
            if extracted and len(extracted.strip()) > 50:
                return ContentCleaner._NormalizeWhitespace(extracted)
        except Exception:
            pass

        # trafilatura 提取失败时回退到基础正则清洗
        return ContentCleaner._StripHtmlFallback(html)

    @staticmethod
    def _StripHtmlFallback(html: str) -> str:
        """基础正则 HTML 清洗（trafilatura 失败时的回退方案）。

        移除 script/style/注释/标签，解码实体，合并空白。
        """
        text = html
        # 移除 script 和 style 块及其内容
        text = re.sub(r"<script[^>]*>.*?</script>", "", text, flags=re.DOTALL | re.IGNORECASE)
        text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL | re.IGNORECASE)
        # 移除 HTML 注释
        text = re.sub(r"<!--.*?-->", "", text, flags=re.DOTALL)
        # 移除所有 HTML 标签
        text = re.sub(r"<[^>]+>", " ", text)
        # 解码常见实体
        text = text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
        text = text.replace("&quot;", '"').replace("&#39;", "'").replace("&nbsp;", " ")
        text = text.replace("&#x27;", "'").replace("&#x2F;", "/")
        return ContentCleaner._NormalizeWhitespace(text)

    @staticmethod
    def _NormalizeWhitespace(text: str) -> str:
        """规范化空白：合并连续空白行，去除首尾空白。"""
        # 将连续空行（3+ 换行）压缩为双换行
        text = re.sub(r"\n{3,}", "\n\n", text)
        # 合并行内多余空白
        lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.splitlines()]
        # 去除首尾空行
        while lines and not lines[0]:
            lines.pop(0)
        while lines and not lines[-1]:
            lines.pop()
        return "\n".join(lines)
