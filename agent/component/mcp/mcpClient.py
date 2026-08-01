"""McpStdioClient —— MCP stdio 传输客户端，基于 JSON-RPC 2.0 与本地子进程通信。

负责：启动 MCP Server 子进程、完成 initialize 握手、tools/list 发现工具、
tools/call 调用工具。消息按行分隔（newline-delimited JSON-RPC），请求/响应
通过 id 配对，期间出现的通知（无 id）被忽略。

仅支持 stdio 传输；http/sse 远程传输由 McpHttpClient 负责。
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from typing import Any, Optional

from common.cancellationToken import CancellationToken
from common.logger import Logger

# stdout 单行可能较大（工具返回大结果），放宽 StreamReader 行长上限
_STREAM_LIMIT = 16 * 1024 * 1024
_PROTOCOL_VERSION = "2024-11-05"
_DEFAULT_READ_TIMEOUT = 120.0  # 单次 MCP 请求读取超时秒数
_STDERR_LOG_INTERVAL = 10.0     # stderr 日志输出最小间隔（秒），避免高频日志刷屏


class McpStdioClient:
    """单个 stdio MCP Server 的 JSON-RPC 客户端。

    生命周期：StartAsync → InitializeAsync → ListToolsAsync / CallToolAsync → Terminate。
    所有请求经同一把锁串行化，避免 DispatchBatch 并发调用时读写流错乱。

    Attributes:
        serverName: 所属 MCP Server 名称。
    """

    def __init__(
        self,
        serverName: str,
        launchCommand: list[str],
        env: dict[str, str] | None = None,
        readTimeout: float = _DEFAULT_READ_TIMEOUT,
    ) -> None:
        self.serverName = serverName
        self._launchCommand = launchCommand
        self._env = env or {}
        self._readTimeout = readTimeout
        self._proc: asyncio.subprocess.Process | None = None
        self._stderrTask: asyncio.Task | None = None
        self._requestId = 0
        self._ioLock = asyncio.Lock()
        self._initialized = False

    # ---- 启动 / 关闭 ----

    async def StartAsync(
        self,
        cancellationToken: Optional[CancellationToken] = None,
    ) -> bool:
        """启动 MCP Server 子进程。

        Returns:
            是否启动成功。
        """
        if not self._launchCommand:
            return False

        mergedEnv = dict(os.environ)
        mergedEnv.update(self._env)

        try:
            self._proc = await asyncio.create_subprocess_exec(
                *self._launchCommand,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=mergedEnv,
                limit=_STREAM_LIMIT,
            )
        except (OSError, ValueError) as exc:
            Logger.Warning(f"MCP[{self.serverName}]: failed to start: {exc}")
            return False

        self._stderrTask = asyncio.ensure_future(self._DrainStderrAsync())
        return True

    def Terminate(self) -> None:
        """同步终止子进程（供 OnDestroy 等同步上下文调用）。"""
        if self._stderrTask is not None and not self._stderrTask.done():
            self._stderrTask.cancel()
        proc = self._proc
        if proc is not None and proc.returncode is None:
            try:
                proc.kill()
            except ProcessLookupError:
                pass
        self._proc = None
        self._initialized = False

    @property
    def IsAlive(self) -> bool:
        """检查子进程是否仍存活。

        仅当 _proc 已创建且 returncode 仍为 None（未退出）时返回 True，
        佛代 CallToolAsync 接返回连接错误时依据此判断是否需要重连。
        """
        return self._proc is not None and self._proc.returncode is None

    async def ReconnectAsync(
        self,
        cancellationToken: Optional[CancellationToken] = None,
    ) -> bool:
        """终止旧进程并重新启动、握手。

        仅当重新 StartAsync 与 InitializeAsync 都成功时返回 True，
        避免子进程起了但没谈成协议后调方误以为已可用。
        """
        self.Terminate()
        if not await self.StartAsync(cancellationToken=cancellationToken):
            return False
        return await self.InitializeAsync(cancellationToken=cancellationToken)

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
            Logger.Warning(f"MCP[{self.serverName}]: initialize failed: {response}")
            return False

        await self._NotifyAsync("notifications/initialized", {})
        self._initialized = True
        return True

    async def ListToolsAsync(
        self,
        cancellationToken: Optional[CancellationToken] = None,
    ) -> list[dict[str, Any]]:
        """tools/list 发现 Server 暴露的工具。

        Returns:
            工具描述字典列表，每项含 name / description / inputSchema。
        """
        response = await self._RequestAsync("tools/list", {}, cancellationToken)
        if response is None or "error" in response:
            Logger.Warning(f"MCP[{self.serverName}]: tools/list failed: {response}")
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

        错误恢复：若首次调用检测到连接丢失（进程已退出或返回 None），
        尝试一次 ReconnectAsync 后重发请求，避免偏远 MCP Server 偊尔崩溃
        后所有后续工具调用都永久失败。

        Returns:
            (是否成功, 文本内容)。
        """
        success, text = await self._CallToolOnceAsync(toolName, arguments, cancellationToken)
        if success:
            return True, text

        # 连接丢失检测：进程已退出或从未启动成功
        if not self.IsAlive:
            Logger.Warning(
                f"MCP[{self.serverName}]: connection lost on tool '{toolName}', "
                f"trying ReconnectAsync once"
            )
            if await self.ReconnectAsync(cancellationToken):
                return await self._CallToolOnceAsync(toolName, arguments, cancellationToken)
            return False, f"MCP[{self.serverName}]: reconnect failed for tool '{toolName}'"

        return success, text

    async def _CallToolOnceAsync(
        self,
        toolName: str,
        arguments: dict[str, Any],
        cancellationToken: Optional[CancellationToken] = None,
    ) -> tuple[bool, str]:
        """单次 tools/call，不含重连，供 CallToolAsync 复用。"""
        response = await self._RequestAsync(
            "tools/call",
            {"name": toolName, "arguments": arguments},
            cancellationToken,
        )
        if response is None:
            return False, f"MCP[{self.serverName}]: no response from tool '{toolName}'"
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
        """发送一个 JSON-RPC 请求并读取配对的响应。"""
        if self._proc is None or self._proc.stdin is None or self._proc.stdout is None:
            return None

        async with self._ioLock:
            self._requestId += 1
            requestId = self._requestId
            payload = {
                "jsonrpc": "2.0",
                "id": requestId,
                "method": method,
                "params": params,
            }

            try:
                self._proc.stdin.write((json.dumps(payload) + "\n").encode("utf-8"))
                await self._proc.stdin.drain()
            except (BrokenPipeError, ConnectionResetError) as exc:
                Logger.Warning(f"MCP[{self.serverName}]: write failed: {exc}")
                return None

            # 读取直到拿到匹配 id 的响应，跳过通知与无关消息
            while True:
                if cancellationToken is not None and cancellationToken.IsCancellationRequested:
                    return None
                try:
                    line = await asyncio.wait_for(
                        self._proc.stdout.readline(),
                        timeout=self._readTimeout,
                    )
                except asyncio.TimeoutError:
                    Logger.Warning(
                        f"MCP[{self.serverName}]: read timed out after {self._readTimeout:.0f}s "
                        f"waiting for response to '{method}'"
                    )
                    return None
                except (asyncio.LimitOverrunError, ValueError) as exc:
                    Logger.Warning(f"MCP[{self.serverName}]: read failed: {exc}")
                    return None
                if not line:
                    return None  # EOF，进程退出
                try:
                    message = json.loads(line.decode("utf-8").strip())
                except json.JSONDecodeError:
                    continue
                if message.get("id") == requestId:
                    return message

    async def _NotifyAsync(self, method: str, params: dict[str, Any]) -> None:
        """发送一个无需响应的 JSON-RPC 通知。"""
        if self._proc is None or self._proc.stdin is None:
            return
        payload = {"jsonrpc": "2.0", "method": method, "params": params}
        try:
            self._proc.stdin.write((json.dumps(payload) + "\n").encode("utf-8"))
            await self._proc.stdin.drain()
        except (BrokenPipeError, ConnectionResetError):
            pass

    async def _DrainStderrAsync(self) -> None:
        """持续排空 stderr，避免管道缓冲写满导致子进程阻塞。

        使用时间窗口聚合：每 _STDERR_LOG_INTERVAL 秒最多输出一次日志，
        累积行数和最近内容，避免高频 stderr 刷屏。
        """
        if self._proc is None or self._proc.stderr is None:
            return
        lastLog = 0.0
        count = 0
        lastLine = ""
        while True:
            try:
                line = await self._proc.stderr.readline()
            except (asyncio.CancelledError, ValueError):
                return
            if not line:
                return
            count += 1
            lastLine = line.decode("utf-8", "replace").rstrip()
            now = time.monotonic()
            if now - lastLog >= _STDERR_LOG_INTERVAL:
                if count == 1:
                    Logger.Debug(f"MCP[{self.serverName}] stderr: {lastLine}")
                else:
                    Logger.Debug(
                        f"MCP[{self.serverName}] stderr ({count} lines): "
                        f"last: {lastLine}"
                    )
                count = 0
                lastLine = ""
                lastLog = now

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
