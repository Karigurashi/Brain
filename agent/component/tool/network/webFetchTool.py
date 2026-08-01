"""WebFetch 工具 —— 从网页获取主要内容。"""

from __future__ import annotations

import ipaddress
import re
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse, urljoin
from urllib.request import Request, build_opener, HTTPRedirectHandler

from ..baseTool import BaseTool, EToolParallelMode
from ..eToolCategory import EToolCategory
from ..toolResult import ToolResult
from ..toolComponent import ToolComponent
from agent.component.contex.eContextLodLevel import EContextLodLevel

MAX_CONTENT_LENGTH = 100000
TIMEOUT_SECONDS = 30
MAX_REDIRECTS = 5
MAX_RETRIES = 3
RETRY_BACKOFF_BASE = 1.0  # seconds

_ANTI_SCRAPE_DOMAINS: set[str] = {
    "eastmoney.com",
    "moomoo.com",
}


@ToolComponent.Register
class FetchContentTool(BaseTool):
    """抓取指定 URL 的网页内容。

    返回纯文本内容，自动移除 HTML 标签。
    内置 SSRF 防护：拒绝指向 localhost / 内网 / 回环 / 链路本地地址的 URL。
    """

    name: str = "webFetch"
    description: str = "Fetch main content from a web page. Must be HTTP/HTTPS URL"
    category: EToolCategory = EToolCategory.NETWORK
    parallelMode: EToolParallelMode = EToolParallelMode.SAFE
    resultLodLevel = EContextLodLevel.DISCARDABLE
    parameters: dict = {
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "HTTP/HTTPS URL"
            },
            "query": {
                "type": "string",
                "description": "Search query in page content"
            },
        },
        "required": ["url"],
    }

    def _Invoke(self, url: str, query: str = "") -> ToolResult:
        try:
            parsed = urlparse(url)
            if parsed.scheme not in ("http", "https"):
                return ToolResult.Fail(
                    f"Unsupported URL scheme: {parsed.scheme}", toolName=self.name
                )

            # ---- SSRF 防护：拒绝内网 / 回环 / 链路本地地址 ----
            if self._IsInternalUrl(url):
                return ToolResult.Fail(
                    f"SSRF blocked: URL points to internal/loopback address: {url}",
                    toolName=self.name,
                )

            # ---- 手动跟随重定向，限制最大次数 ----
            raw, contentType, finalUrl = self._FetchWithRetry(url)

            truncated = len(raw) > MAX_CONTENT_LENGTH
            raw = raw[: MAX_CONTENT_LENGTH + 1]

            # 从 Content-Type 提取 charset 作为首选编码
            charsetFromHeader = self._ParseCharset(contentType)

            # 编码检测链：header charset → utf-8 → 中文编码 → latin-1(fallback)
            text = ""
            encodings = ["utf-8", "gb18030", "gbk", "gb2312", "latin-1"]
            if charsetFromHeader and charsetFromHeader.lower() not in [e.lower() for e in encodings]:
                encodings.insert(0, charsetFromHeader.lower())

            for encoding in encodings:
                try:
                    text = raw.decode(encoding)
                    break
                except (UnicodeDecodeError, LookupError):
                    continue
            else:
                text = raw.decode("utf-8", errors="replace")

            isHtml = "text/html" in contentType.lower() or "<html" in text[:500].lower()

            # ---- 正文清洗（trafilatura），替代原正则 _StripHtml ----
            from .contentCleaner import ContentCleaner
            cleanText = ContentCleaner.Clean(text, isHtml=isHtml)

            if truncated:
                cleanText = cleanText[:MAX_CONTENT_LENGTH] + "\n\n... (content truncated)"

            # ---- 页内搜索 ----
            if query:
                cleanText = self._SearchInContent(cleanText, query)

            header = f"[Fetched from: {finalUrl}]\n"
            return ToolResult.Ok(header + cleanText, toolName=self.name)

        except URLError as exc:
            return ToolResult.Fail(f"Failed to fetch URL: {exc}", toolName=self.name)
        except ValueError as exc:
            return ToolResult.Fail(str(exc), toolName=self.name)
        except Exception as exc:
            return ToolResult.Fail(f"Fetch failed: {exc}", toolName=self.name)

    def _IsInternalUrl(self, url: str) -> bool:
        """检测 URL 是否指向内网 / 回环 / 链路本地地址。

        Returns:
            True 表示内网地址（应拒绝）；False 表示外网域名或 IP（允许）。
        """
        parsed = urlparse(url)
        hostname = parsed.hostname
        if not hostname:
            return True
        if hostname in ("localhost", "127.0.0.1", "::1", "0.0.0.0"):
            return True
        try:
            ip = ipaddress.ip_address(hostname)
            return ip.is_private or ip.is_loopback or ip.is_link_local
        except ValueError:
            # 域名而非 IP，允许通过（DNS 解析后的二次校验在生产环境另外处理）
            return False

    def _FetchWithRedirects(self, url: str) -> tuple[bytes, str, str]:
        """禁用 urllib 自动重定向，手动跟随并对每跳进行 SSRF 校验。

        Returns:
            (rawBytes, contentType, finalUrl)
        """
        # 自定义 opener：拒绝自动重定向，便于手动控制次数
        class _NoRedirect(HTTPRedirectHandler):
            def redirect_request(self, req, fp, code, msg, headers, newurl):  # noqa: D401,N802
                return None  # 阻止自动跟随

        opener = build_opener(_NoRedirect())

        currentUrl = url
        for hop in range(MAX_REDIRECTS + 1):
            req = Request(currentUrl, headers=self._BuildHeaders(currentUrl))
            try:
                resp = opener.open(req, timeout=TIMEOUT_SECONDS)
                contentType = resp.headers.get("Content-Type", "")
                raw = resp.read(MAX_CONTENT_LENGTH + 1)
                resp.close()
                return raw, contentType, currentUrl
            except HTTPError as exc:
                # urllib 在重定向被阻止时抛出 HTTPError(code=3xx)
                if 300 <= exc.code < 400:
                    location = exc.headers.get("Location") if exc.headers else None
                    if not location:
                        raise URLError(f"Redirect without Location header: {exc.code}")
                    nextUrl = urljoin(currentUrl, location)
                    if hop >= MAX_REDIRECTS:
                        raise URLError(
                            f"Too many redirects (>{MAX_REDIRECTS}) starting from {url}"
                        )
                    if self._IsInternalUrl(nextUrl):
                        raise ValueError(
                            f"SSRF blocked on redirect: {nextUrl} resolves to internal address"
                        )
                    currentUrl = nextUrl
                    continue
                raise

        raise URLError(f"Too many redirects (>{MAX_REDIRECTS}) starting from {url}")

    @staticmethod
    def _BuildHeaders(url: str) -> dict[str, str]:
        """构建完整的浏览器伪装请求头。"""
        parsed = urlparse(url)
        referer = f"{parsed.scheme}://{parsed.netloc}/"
        return {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/125.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7",
            "Referer": referer,
            "Cache-Control": "max-age=0",
            "Connection": "keep-alive",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
            "Upgrade-Insecure-Requests": "1",
            "DNT": "1",
        }

    def _IsAntiScrapeSite(self, url: str) -> bool:
        """检测 URL 是否属于已知反爬站点。"""
        parsed = urlparse(url)
        hostname = parsed.hostname or ""
        return any(domain in hostname for domain in _ANTI_SCRAPE_DOMAINS)

    def _FetchWithRetry(self, url: str) -> tuple[bytes, str, str]:
        """对已知反爬站点进行指数退避重试的抓取。

        Returns:
            (rawBytes, contentType, finalUrl)
        """
        isAntiScrape = self._IsAntiScrapeSite(url)
        maxAttempts = MAX_RETRIES if isAntiScrape else 1
        lastError: URLError | None = None

        for attempt in range(maxAttempts):
            try:
                return self._FetchWithRedirects(url)
            except URLError as exc:
                lastError = exc
                # 仅对 socket 级别错误重试，不含 HTTP 错误和重定向错误
                isSocketError = isinstance(exc.reason, OSError)
                if not isAntiScrape or not isSocketError or attempt >= maxAttempts - 1:
                    raise
                backoff = RETRY_BACKOFF_BASE * (2 ** attempt)
                time.sleep(backoff)

        # 理论上不会到达，仅做类型安全兜底
        raise lastError  # type: ignore[misc]

    @staticmethod
    def _ParseCharset(contentType: str) -> str:
        """从 Content-Type 头提取 charset 参数。

        Returns:
            charset 值（如 'gbk'），无则返回空字符串。
        """
        match = re.search(r"charset=([^\s;]+)", contentType, re.IGNORECASE)
        return match.group(1).strip().strip('"\'') if match else ""

    @staticmethod
    def _SearchInContent(text: str, query: str) -> str:
        """在文本中搜索与 query 相关的段落并返回摘要。

        将文本按段落拆分，对 query 的每个关键词做大小写不敏感匹配，
        返回匹配段落及其前后各一段上下文，去重合并。

        Args:
            text: 清洗后的纯文本。
            query: 搜索查询字符串。

        Returns:
            匹配段落摘要，或未匹配时返回内容前部。
        """
        if not query.strip():
            return text

        keywords = [kw.strip().lower() for kw in query.split() if kw.strip()]
        if not keywords:
            return text

        # 按空行拆分为段落块
        paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
        if not paragraphs:
            return text

        # 标记匹配段落索引
        matchedIndices: set[int] = set()
        for i, para in enumerate(paragraphs):
            paraLower = para.lower()
            if any(kw in paraLower for kw in keywords):
                matchedIndices.add(i)

        if not matchedIndices:
            # 无匹配：返回内容前部（最多 2000 字符）作为预览
            preview = text[:2000]
            if len(text) > 2000:
                preview += "\n... (no matches found for query, showing first 2000 chars)"
            return f"[No exact matches for '{query}' in page content. Preview:]\n\n{preview}"

        # 扩展上下文：匹配段落前后各 1 段
        contextIndices: set[int] = set()
        for idx in matchedIndices:
            contextIndices.add(idx)
            if idx > 0:
                contextIndices.add(idx - 1)
            if idx < len(paragraphs) - 1:
                contextIndices.add(idx + 1)

        # 按原始顺序输出，用 '...' 标记跳过的段落
        resultLines: list[str] = []
        lastIdx = -2
        for i in sorted(contextIndices):
            if i > lastIdx + 1:
                resultLines.append("...")
            resultLines.append(paragraphs[i])
            lastIdx = i

        matchedCount = len(matchedIndices)
        totalCount = len(paragraphs)
        header = f"[Page content matching '{query}': {matchedCount}/{totalCount} paragraphs]\n\n"
        return header + "\n\n".join(resultLines)
