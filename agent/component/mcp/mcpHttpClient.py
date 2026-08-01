"""McpHttpClient —— MCP HTTP 传输客户端，基于 JSON-RPC 2.0 通过 HTTP POST 与远程 MCP Server 通信。

对标 McpStdioClient，提供相同的异步接口：StartAsync / InitializeAsync / ListToolsAsync / CallToolAsync / Terminate。
使用 requests 库通过 asyncio.to_thread 做异步 HTTP 调用。
支持 http 和 sse 两种远程传输协议。
"""

from __future__ import annotations

import asyncio
import json
import re
from typing import Any, Optional

import requests

from common.cancellationToken import CancellationToken
from common.logger import Logger

_PROTOCOL_VERSION = "2024-11-05"


class McpHttpClient:
    """单个 HTTP/SSE MCP Server 的 JSON-RPC 客户端。

    Attributes:
        serverName: 所属 MCP Server 名称。
        url: MCP Server 端点 URL。
    """

    def __init__(
        self,
        serverName: str,
        url: str,
    ) -> None:
        self.serverName = serverName
        self.url = url
        self._requestId = 0
        self._ioLock = asyncio.Lock()

    # ---- 生命周期（与 McpStdioClient 对齐） ----

    async def StartAsync(
        self,
        cancellationToken: Optional[CancellationToken] = None,
    ) -> bool:
        """HTTP 无状态，无需启动子进程，始终返回 True。"""
        return True

    def Terminate(self) -> None:
        """HTTP 无状态，无需清理资源。"""
        pass

    @property
    def IsAlive(self) -> bool:
        """HTTP 无状态，始终返回 True。"""
        return True

    async def ReconnectAsync(
        self,
        cancellationToken: Optional[CancellationToken] = None,
    ) -> bool:
        """HTTP 无状态，重连即重新握手。"""
        return await self.InitializeAsync(cancellationToken)

    # ---- 握手与能力 ----

    async def InitializeAsync(
        self,
        cancellationToken: Optional[CancellationToken] = None,
    ) -> bool:
        """执行 MCP initialize 握手并发送 initialized 通知。"""
        response = await self._RequestAsync(
            "initialize",
            {
                "protocolVersion": _PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "brain-agent", "version": "1.0"},
            },
            cancellationToken,
        )
        if response is None or "error" in response:
            Logger.Warning(f"MCP-HTTP[{self.serverName}]: initialize failed: {response}")
            return False

        await self._NotifyAsync("notifications/initialized", {})
        return True

    async def ListToolsAsync(
        self,
        cancellationToken: Optional[CancellationToken] = None,
    ) -> list[dict[str, Any]]:
        """tools/list 发现 Server 暴露的工具。"""
        response = await self._RequestAsync("tools/list", {}, cancellationToken)
        if response is None or "error" in response:
            Logger.Warning(f"MCP-HTTP[{self.serverName}]: tools/list failed: {response}")
            return []
        result = response.get("result", {})
        tools = result.get("tools", [])
        return tools if isinstance(tools, list) else []

    async def CallToolAsync(
        self,
        toolName: str,
        arguments: dict[str, Any],
        cancellationToken: Optional[CancellationToken] = None,
    ) -> tuple[bool, str]:
        """tools/call 调用指定工具。

        Returns:
            (是否成功, 文本内容)。
        """
        response = await self._RequestAsync(
            "tools/call",
            {"name": toolName, "arguments": arguments},
            cancellationToken,
        )
        if response is None:
            return False, f"MCP-HTTP[{self.serverName}]: no response from tool '{toolName}'"
        if "error" in response:
            return False, f"MCP error: {response['error']}"

        result = response.get("result", {})
        isError = bool(result.get("isError", False))
        text = self._ExtractContentText(result.get("content", []))
        return (not isError), text

    # ---- 内部 JSON-RPC ----

    async def _RequestAsync(
        self,
        method: str,
        params: dict[str, Any],
        cancellationToken: Optional[CancellationToken] = None,
    ) -> dict[str, Any] | None:
        """发送 JSON-RPC 请求到 HTTP MCP Server。"""
        async with self._ioLock:
            self._requestId += 1
            requestId = self._requestId
            payload = {
                "jsonrpc": "2.0",
                "id": requestId,
                "method": method,
                "params": params,
            }

            if cancellationToken is not None and cancellationToken.IsCancellationRequested:
                return None

            try:
                response = await asyncio.to_thread(
                    requests.post,
                    self.url,
                    json=payload,
                    headers={
                        "Content-Type": "application/json",
                        "Accept": "application/json, text/event-stream",
                    },
                    timeout=120,
                    proxies={"http": None, "https": None},
                )
                response.raise_for_status()
                raw = response.text
            except requests.RequestException as exc:
                Logger.Warning(f"MCP-HTTP[{self.serverName}]: request failed: {exc}")
                return None

            if not raw:
                return None

            # 响应可能是直 JSON，也可能是 SSE 格式（data: {...}\n\n）
            if raw.startswith("{"):
                try:
                    return json.loads(raw)
                except json.JSONDecodeError:
                    Logger.Warning(f"MCP-HTTP[{self.serverName}]: bad JSON: {raw[:200]}")
                    return None

            # SSE 格式：data: {...JSON...}，括号计数处理嵌套
            for line in raw.split('\n'):
                stripped = line.strip()
                if stripped.startswith('data:'):
                    content = stripped[5:].strip()
                    if content.startswith('{'):
                        depth = 0
                        end = -1
                        for i, ch in enumerate(content):
                            if ch == '{':
                                depth += 1
                            elif ch == '}':
                                depth -= 1
                                if depth == 0:
                                    end = i + 1
                                    break
                        if end > 0:
                            content = content[:end]
                        try:
                            return json.loads(content)
                        except json.JSONDecodeError:
                            pass

            Logger.Warning(f"MCP-HTTP[{self.serverName}]: unrecognized response: {raw[:200]}")
            return None

    async def _NotifyAsync(self, method: str, params: dict[str, Any]) -> None:
        """发送 JSON-RPC 通知（无需响应）。"""
        payload = {"jsonrpc": "2.0", "method": method, "params": params}
        try:
            await asyncio.to_thread(
                requests.post,
                self.url,
                json=payload,
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json, text/event-stream",
                },
                timeout=30,
                proxies={"http": None, "https": None},
            )
        except Exception:
            pass

    @staticmethod
    def _ExtractContentText(content: Any) -> str:
        """从 MCP tools/call 结果的 content 数组提取文本。"""
        if not isinstance(content, list):
            return str(content)
        parts: list[str] = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                parts.append(str(block.get("text", "")))
            elif isinstance(block, dict):
                parts.append(json.dumps(block, ensure_ascii=False))
        return "\n".join(parts)
