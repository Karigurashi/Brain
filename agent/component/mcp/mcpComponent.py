"""McpComponent —— 将 MCP Server 管理封装为可挂载的 IComponent。

挂载到 BaseAgent 后，通过 BaseAgent.GetComponent(McpComponent) 获取
MCP Server 注册表，支持 .mcp.json 加载与多种传输协议。
对标 Claude Code MCP 的 claude mcp add/remove/list 命令体系。
"""

from __future__ import annotations

import asyncio
import json
import os
from typing import Any, Optional, TYPE_CHECKING

from agent.core.baseComponent import BaseComponent
from common.cancellationToken import CancellationToken
from common.logger import Logger

from .eMcpTransport import EMcpTransport
from .mcpServerConfig import McpServerConfig

if TYPE_CHECKING:
    from agent.core.baseAgent import BaseAgent
    from .mcpClient import McpStdioClient
    from .mcpHttpClient import McpHttpClient
    from .mcpTool import McpTool


class McpComponent(BaseComponent):
    """MCP Server 管理组件 —— 持有 MCP Server 配置注册表。

    挂载到 BaseAgent 后自动可用，通过 GetComponent(McpComponent) 获取。
    对标 Claude Code MCP 的 Server 管理：
    - 支持 stdio / http / sse 三种传输协议。
    - 支持 .mcp.json 批量加载。

    用法::

        agent = BaseAgent()
        mcpComp = McpComponent()
        agent.AddComponent(mcpComp)
        mcpComp.LoadFromMCPJson(".mcp.json")
    """

    def __init__(self) -> None:
        self._servers: dict[str, McpServerConfig] = {}
        self._clients: list["McpStdioClient | McpHttpClient"] = []

    # ---- 生命周期 ----

    def OnInitialize(self, agent: BaseAgent) -> None:
        """挂载后初始化。"""
        pass

    def OnDestroy(self) -> None:
        """从 BaseAgent 卸载时回调，终止全部 MCP 子进程并清空注册。"""
        for client in self._clients:
            client.Terminate()
        self._clients.clear()
        self._servers.clear()

    # ---- 注册 ----

    def Register(self, config: McpServerConfig) -> None:
        """注册一个 MCP Server 配置（同名覆盖）。"""
        if not config.name:
            raise ValueError("McpServerConfig must have a non-empty name")
        self._servers[config.name] = config

    def Unregister(self, name: str) -> None:
        """移除指定 Server。"""
        self._servers.pop(name, None)

    # ---- 查询 ----

    def Get(self, name: str) -> McpServerConfig | None:
        """按名称获取 Server 配置。"""
        return self._servers.get(name)

    def GetAll(self) -> dict[str, McpServerConfig]:
        """获取所有已注册 Server 配置的副本。"""
        return dict(self._servers)

    def GetEnabled(self) -> list[McpServerConfig]:
        """获取所有已启用的 Server。"""
        return [s for s in self._servers.values() if s.enabled]

    def GetByTransport(self, transport: EMcpTransport) -> list[McpServerConfig]:
        """按传输协议筛选。"""
        return [s for s in self._servers.values() if s.transport == transport]

    def GetByScope(self, scope: str) -> list[McpServerConfig]:
        """按作用域筛选。"""
        return [s for s in self._servers.values() if s.scope == scope]

    # ---- 序列化 ----

    def ToMCPJson(self) -> str:
        """导出为 .mcp.json 兼容的 JSON 字符串。"""
        serversDict: dict[str, dict[str, Any]] = {}
        for name, config in self._servers.items():
            d: dict[str, Any] = {
                "type": config.transport.ToLabel(),
                "scope": config.scope,
            }
            if config.transport == EMcpTransport.STDIO:
                if config.command:
                    d["command"] = config.command
                if config.args:
                    d["args"] = config.args
            elif config.transport in (EMcpTransport.HTTP, EMcpTransport.SSE):
                if config.url:
                    d["url"] = config.url
            if config.env:
                d["env"] = config.env
            if config.tools:
                d["tools"] = config.tools
            if config.toolsMax != McpServerConfig._DEFAULT_TOOLS_MAX:
                d["toolsMax"] = config.toolsMax
            serversDict[name] = d
        result = {"mcpServers": serversDict}
        return json.dumps(result, indent=2, ensure_ascii=False)

    def LoadFromMCPJson(self, filePath: str) -> int:
        """从 .mcp.json 文件加载所有 Server 配置。

        Returns:
            成功加载的 Server 数量。
        """
        if not os.path.isfile(filePath):
            return 0

        try:
            with open(filePath, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            return 0

        serversDict = data.get("mcpServers", {})
        count = 0
        for name, serverData in serversDict.items():
            if isinstance(serverData, dict):
                transportRaw = serverData.get("type", serverData.get("transport", "stdio"))
                transport = EMcpTransport.FromLabel(transportRaw)
                config = McpServerConfig(
                    name=name,
                    transport=transport,
                    command=serverData.get("command", ""),
                    args=serverData.get("args", []),
                    url=serverData.get("url", ""),
                    env=serverData.get("env", {}),
                    scope=serverData.get("scope", "local"),
                    enabled=serverData.get("enabled", True),
                    tools=serverData.get("tools", []),
                    toolsMax=serverData.get("toolsMax", 0),
                )
                self.Register(config)
                count += 1

        return count

    # ---- 真实连接与工具发现 ----

    _CONNECT_ALL_TIMEOUT = 30.0

    async def ConnectAllAsync(
        self,
        cancellationToken: Optional[CancellationToken] = None,
    ) -> list["McpTool"]:
        """连接全部已启用的 MCP Server，发现并适配其工具。

        整体超时保护：包装 _ConnectAllInternalAsync，超过 _CONNECT_ALL_TIMEOUT 后
        返回空列表，避免起动阶段某个偏远 Server 永久阻塞拖垮整个 Agent。
        任一 Server 失败仅记录日志并跳过，不影响其他 Server 与整体 Agent 构建。

        Returns:
            可注入 ToolComponent 的 McpTool 列表。
        """
        try:
            return await asyncio.wait_for(
                self._ConnectAllInternalAsync(cancellationToken),
                timeout=self._CONNECT_ALL_TIMEOUT,
            )
        except asyncio.TimeoutError:
            Logger.Warning(
                f"MCP ConnectAll timed out after {self._CONNECT_ALL_TIMEOUT:.0f}s, "
                f"returning {len(self._clients)} partially connected client(s)"
            )
            return []

    async def _ConnectAllInternalAsync(
        self,
        cancellationToken: Optional[CancellationToken] = None,
    ) -> list["McpTool"]:
        """ConnectAllAsync 内部实现，不含超时包装。

        所有已启用 Server 并行启动、握手、发现工具，
        单 Server 异常隔离，不影响其余 Server。
        """
        servers = self.GetEnabled()
        if not servers:
            return []

        tasks = [
            self._ConnectOneServerAsync(s, cancellationToken)
            for s in servers
        ]
        results: list[tuple[str, list["McpTool"]]] = await asyncio.gather(
            *tasks, return_exceptions=True,
        )

        allTools: list["McpTool"] = []
        for result in results:
            if isinstance(result, BaseException):
                Logger.Warning(f"MCP connect task failed with exception: {result}")
                continue
            serverName, tools = result
            if tools:
                allTools.extend(tools)
        return allTools

    async def _ConnectOneServerAsync(
        self,
        server: McpServerConfig,
        cancellationToken: Optional[CancellationToken] = None,
    ) -> tuple[str, list["McpTool"]]:
        """连接单台 MCP Server 并发现工具，异常隔离：失败返回空列表。

        支持 stdio / http / sse 三种传输协议。
        仅当 StartAsync → InitializeAsync → ListToolsAsync 全链路成功
        后才将 client 加入 _clients 并返回工具列表，中途失败则清理资源。
        """
        from .mcpClient import McpStdioClient
        from .mcpHttpClient import McpHttpClient
        from .mcpTool import McpTool

        # ---- stdio ----
        if server.transport == EMcpTransport.STDIO:
            launchCommand = server.GetLaunchCommand()
            if not launchCommand:
                Logger.Warning(f"MCP[{server.name}]: missing launch command, skipped")
                return server.name, []

            client = McpStdioClient(server.name, launchCommand, server.ResolveEnv())
            if not await client.StartAsync(cancellationToken):
                return server.name, []

            if not await client.InitializeAsync(cancellationToken):
                client.Terminate()
                return server.name, []

        # ---- http / sse ----
        elif server.transport in (EMcpTransport.HTTP, EMcpTransport.SSE):
            if not server.url:
                Logger.Warning(f"MCP[{server.name}]: missing url for http/sse, skipped")
                return server.name, []

            client = McpHttpClient(server.name, server.url)
            if not await client.StartAsync(cancellationToken):
                return server.name, []

            if not await client.InitializeAsync(cancellationToken):
                client.Terminate()
                return server.name, []

        else:
            Logger.Warning(
                f"MCP[{server.name}]: unknown transport '{server.transport.ToLabel()}', skipped"
            )
            return server.name, []

        discovered = await client.ListToolsAsync(cancellationToken)
        tools: list["McpTool"] = []

        # ---- 白名单过滤 ----
        whitelist = server.tools
        if whitelist:
            discovered = [s for s in discovered if s.get("name", "") in whitelist]

        # ---- 上限截断 ----
        maxTools = server.toolsMax
        totalCount = len(discovered)
        if maxTools > 0 and totalCount > maxTools:
            Logger.Warning(
                f"MCP[{server.name}]: {totalCount} tools discovered, "
                f"truncating to first {maxTools} (set toolsMax=0 or tools whitelist to override)"
            )
            discovered = discovered[:maxTools]

        for spec in discovered:
            name = spec.get("name", "")
            if not name:
                continue
            tools.append(McpTool(
                client=client,
                serverName=server.name,
                remoteName=name,
                description=spec.get("description", ""),
                parameters=spec.get("inputSchema", {}),
            ))

        self._clients.append(client)
        Logger.Info(f"MCP[{server.name}]: connected via {server.transport.ToLabel()}, {len(tools)}/{totalCount} tool(s) registered")
        return server.name, tools

    # ---- 管理 ----

    def Count(self) -> int:
        """已注册 Server 总数。"""
        return len(self._servers)

    def Clear(self) -> None:
        """清空所有注册（谨慎使用）。"""
        self._servers.clear()
