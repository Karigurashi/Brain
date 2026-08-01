"""MCP Server 配置对象 —— 封装单个 MCP Server 的连接信息。

对标 Claude Code 的 .mcp.json 配置项和 claude mcp add 命令参数。
"""

from __future__ import annotations

import os
import re

from .eMcpTransport import EMcpTransport

# 环境变量占位符正则: ${VAR_NAME}
_ENV_PATTERN = re.compile(r"\$\{(\w+)\}")


def _ReplaceEnvVar(m: re.Match) -> str:
    """re.sub 回调：将 ${VAR} 替换为环境变量值，无对应值时保留原样。"""
    return os.environ.get(m.group(1), m.group(0))


class McpServerConfig:
    """单个 MCP Server 的静态配置，包含传输方式、连接参数和作用域。

    Attributes:
        name: Server 名称（唯一标识）。
        transport: 传输协议。
        command: stdio 模式下的启动命令（如 ``"npx"``）。
        args: stdio 模式下的命令参数列表。
        url: http/sse 模式下的服务 URL。
        env: 环境变量字典（支持 ``${VAR}`` 占位符）。
        scope: 作用域（``"local"`` / ``"project"`` / ``"user"``），对标 Claude Code。
        enabled: 是否启用。
        tools: 工具白名单（空列表 = 全部注册）。
        toolsMax: 单个 Server 最多注册的工具数（0 = 不限制，默认 30）。
    """

    _DEFAULT_TOOLS_MAX = 30

    def __init__(
        self,
        name: str,
        transport: EMcpTransport = EMcpTransport.STDIO,
        command: str = "",
        args: list[str] | None = None,
        url: str = "",
        env: dict[str, str] | None = None,
        scope: str = "local",
        enabled: bool = True,
        tools: list[str] | None = None,
        toolsMax: int = 0,
    ) -> None:
        self.name = name
        self.transport = transport
        self.command = command
        self.args = args or []
        self.url = url
        self.env = env or {}
        self.scope = scope
        self.enabled = enabled
        self.tools = tools or []
        self.toolsMax = toolsMax if toolsMax > 0 else self._DEFAULT_TOOLS_MAX

    # ---- 工具方法 ----

    def GetLaunchCommand(self) -> list[str] | None:
        """获取 stdio 模式下的完整启动命令。

        Returns:
            ``[command] + args`` 列表，非 stdio 模式返回 None。
        """
        if self.transport != EMcpTransport.STDIO:
            return None
        if not self.command:
            return None
        return [self.command] + self.args

    def ResolveEnv(self) -> dict[str, str]:
        """解析环境变量中的 ``${VAR}`` 占位符。

        从系统环境中读取实际值替换，占位符无对应值时保留原样。
        """
        resolved: dict[str, str] = {}
        for key, value in self.env.items():
            resolved[key] = _ENV_PATTERN.sub(_ReplaceEnvVar, value)
        return resolved

    def IsStdio(self) -> bool:
        """是否为 stdio 传输。"""
        return self.transport == EMcpTransport.STDIO

    def IsRemote(self) -> bool:
        """是否为远程传输（http 或 sse）。"""
        return self.transport in (EMcpTransport.HTTP, EMcpTransport.SSE)
