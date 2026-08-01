"""WebSearch 工具 —— 探索网络获取实时信息。"""

from __future__ import annotations

import json

import httpx

from ..baseTool import BaseTool, EToolParallelMode
from ..eToolCategory import EToolCategory
from ..toolResult import ToolResult
from ..toolComponent import ToolComponent
from agent.component.contex.eContextLodLevel import EContextLodLevel
from agent.component.data.dataComponent import DataComponent

TAVILY_API_ENDPOINT = "https://api.tavily.com/search"
MAX_RESULTS = 10
TIMEOUT_SECONDS = 30

@ToolComponent.Register
class SearchWebTool(BaseTool):
    """使用 Tavily Search API 搜索网页内容。

    Tavily 专为 AI Agent / RAG 场景设计，搜索结果包含标题、URL 和内容摘要。

    API Key 通过 ``AgentConfig.tavilyApiKey`` 配置。

    免费申请（1,000 次/月，无需信用卡）：https://tavily.com/
    """

    name: str = "webSearch"
    description: str = "Search web. timeRange controls recency"
    category: EToolCategory = EToolCategory.NETWORK
    parallelMode: EToolParallelMode = EToolParallelMode.SAFE
    parameters: dict = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Search query. 1-100 chars"
            },
            "timeRange": {
                "type": "string",
                "enum": ["day", "week", "month", "year"],
                "description": "Filter results by recency. Omit for no limit"
            },
        },
        "required": ["query"],
    }
    timeout: float | None = TIMEOUT_SECONDS
    resultLodLevel = EContextLodLevel.DISCARDABLE

    def _Invoke(self, query: str, timeRange: str = "month") -> ToolResult:
        try:
            dataComp = self._agent.GetComponent(DataComponent)
            apiKey = dataComp.config.tavilyApiKey
            if not apiKey:
                return ToolResult.Fail(
                    "Tavily API key not configured. Set AgentConfig.tavilyApiKey. "
                    "Get a free key (1,000 queries/month, no credit card) at: https://tavily.com/",
                    toolName=self.name,
                )

            rawJson = self._CallTavilyApi(apiKey, query, MAX_RESULTS, timeRange)
            results = self._ParseResponse(rawJson)

            if not results:
                return ToolResult.Ok(
                    f"No search results found for: '{query}'",
                    toolName=self.name,
                )

            formatted = self._FormatResults(query, results, timeRange)
            return ToolResult.Ok(formatted, toolName=self.name)

        except Exception as exc:
            return ToolResult.Fail(f"Search failed: {exc}", toolName=self.name)

    # ---- API 调用 ----

    @staticmethod
    def _CallTavilyApi(apiKey: str, query: str, maxResults: int = MAX_RESULTS, timeRange: str = "NoLimit") -> str:
        """调用 Tavily Search API，返回原始 JSON 字符串。

        Tavily 使用 POST + JSON Body + Bearer Token 认证。

        Args:
            apiKey: Tavily API 密钥。
            query: 搜索查询字符串。
            maxResults: 返回结果数量。
            timeRange: 时间范围过滤（day/week/month/year），空字符串表示不限。

        Returns:
            API 响应的原始 JSON 字符串。

        Raises:
            httpx.HTTPStatusError: HTTP 错误（4xx/5xx）。
            httpx.RequestError: 网络/SSL 错误。
            ValueError: 响应非合法 JSON。
        """
        bodyDict: dict = {
            "query": query,
            "max_results": maxResults,
            "search_depth": "basic",
        }
        if timeRange:
            bodyDict["time_range"] = timeRange

        response = httpx.post(
            TAVILY_API_ENDPOINT,
            json=bodyDict,
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {apiKey}",
            },
            timeout=TIMEOUT_SECONDS,
        )
        response.raise_for_status()
        return response.text

    # ---- 响应解析 ----

    @staticmethod
    def _ParseResponse(rawJson: str) -> list[dict]:
        """解析 Tavily API JSON 响应，提取搜索结果。

        Tavily API 响应结构::

            {
                "query": "...",
                "results": [
                    {"title": "标题", "url": "https://...", "content": "摘要", "score": 0.81},
                    ...
                ]
            }

        Args:
            rawJson: API 返回的原始 JSON 字符串。

        Returns:
            搜索结果列表: [{"title": str, "url": str, "snippet": str}, ...]
        """
        data = json.loads(rawJson)
        items = data.get("results", [])
        if not items:
            return []

        results: list[dict] = []
        for item in items:
            title = (item.get("title") or "").strip()
            url = (item.get("url") or "").strip()
            content = (item.get("content") or "").strip()
            if not title or not url:
                continue
            results.append({"title": title, "url": url, "snippet": content})

        return results

    # ---- 结果格式化 ----

    @staticmethod
    def _FormatResults(query: str, results: list[dict], timeRange: str = "NoLimit") -> str:
        """将搜索结果格式化为 LLM 可消费的文本。

        Args:
            query: 搜索查询字符串。
            results: ParseResponse 返回的结果列表。
            timeRange: 时间范围过滤参数。

        Returns:
            格式化后的文本字符串。
        """
        header = f"[Web search results for: '{query}' ({len(results)} results)"
        if timeRange:
            header += f", timeRange: {timeRange}"
        header += "]\n"
        lines = [header]
        for i, r in enumerate(results, 1):
            lines.append(f"{i}. {r['title']}")
            lines.append(f"   URL: {r['url']}")
            lines.append(f"   {r['snippet']}")
            lines.append("")
        return "\n".join(lines)


