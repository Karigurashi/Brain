"""McpTool —— 将 MCP Server 暴露的远程工具适配为框架内的 BaseTool。

每个 McpTool 持有一个 McpStdioClient 引用与远程工具名，ExecuteAsync 时
通过 client.CallToolAsync 转发调用，把结果包装为 ToolResult。
工具名以 ``mcp__{server}__{tool}`` 命名，避免与本地工具或跨 Server 冲突。
"""

from __future__ import annotations

from typing import Any

from agent.component.tool.baseTool import BaseTool
from agent.component.tool.eToolCategory import EToolCategory
from agent.component.tool.toolResult import ToolResult
from llm.provider.chatMessage import ToolSpec

from .mcpClient import McpStdioClient
from .mcpHttpClient import McpHttpClient


class McpTool(BaseTool):
    """MCP 远程工具适配器。

    动态实例（非装饰器注册），由 McpComponent 在连接 Server 后创建并注入
    ToolComponent。name/description/parameters 来自 Server 的 tools/list。

    注意：每个 McpTool 实例的 name/description/parameters 均不同，
    因此覆盖基类 ToToolSpec() 禁止类级缓存，每实例动态构建 ToolSpec。
    """

    category: EToolCategory = EToolCategory.CUSTOM
    timeout: float | None = 120.0

    def __init__(
        self,
        client: McpStdioClient | McpHttpClient,
        serverName: str,
        remoteName: str,
        description: str,
        parameters: dict[str, Any],
    ) -> None:
        self._client = client
        self._remoteName = remoteName
        self.name = f"mcp_{serverName}_{remoteName}"
        self.description = description or f"MCP tool '{remoteName}' from server '{serverName}'"
        self.parameters = parameters or {"type": "object", "properties": {}}

    def ToToolSpec(self) -> ToolSpec:
        """覆盖基类：禁用类级缓存，每次动态构建。

        McpTool 每个实例的 name/description/parameters 均不同，
        基类的 cls._cachedToolSpec 类级缓存会导致所有实例复用首个实例的 ToolSpec。
        """
        return ToolSpec(
            name=self.name,
            description=self.description,
            parameters=self.parameters,
        )

    async def _InvokeAsync(self, **kwargs) -> ToolResult:
        """转发调用到 MCP Server。

        MCP 工具参数为 Server 动态声明的 JSON Schema，键名与数量在运行时确定，
        因此使用 **kwargs 接收动态参数后转为 dict 转发，属于例外情况。
        """
        success, content = await self._client.CallToolAsync(self._remoteName, dict(kwargs))
        if success:
            return ToolResult.Ok(content, toolName=self.name)
        return ToolResult.Fail(content, toolName=self.name)
