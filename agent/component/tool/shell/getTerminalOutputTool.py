"""GetTerminalOutput 工具 —— 获取后台终端命令的输出。"""

from __future__ import annotations

import asyncio

from ..baseTool import BaseTool, EToolParallelMode
from ..eToolCategory import EToolCategory
from ..toolResult import ToolResult
from ..toolComponent import ToolComponent
from agent.component.contex.eContextLodLevel import EContextLodLevel

MAX_OUTPUT_LENGTH = 50000


@ToolComponent.Register
class GetTerminalOutputTool(BaseTool):
    """获取之前启动的终端命令的输出。

    根据 Shell（is_background=true）返回的 terminal_id 查找后台进程，
    等待其完成并返回 stdout/stderr 内容。

    通过 ToolComponent 获取 ShellTool 实例，访问其后台进程注册表。
    """

    name: str = "getTerminalOutput"
    description: str = "Get output of a background terminal command by terminal_id"
    category: EToolCategory = EToolCategory.SHELL
    parallelMode: EToolParallelMode = EToolParallelMode.SAFE
    resultLodLevel = EContextLodLevel.DISCARDABLE
    parameters: dict = {
        "type": "object",
        "properties": {
            "terminal_id": {
                "type": "string",
                "description": "Terminal command ID"
            },
            "wait_seconds": {
                "type": "integer",
                "description": "Wait seconds for completion"
            },
        },
        "required": ["terminal_id"],
    }

    async def _InvokeAsync(self, terminal_id: str, wait_seconds: int = 2) -> ToolResult:
        from ..toolComponent import ToolComponent as _TC
        from .shellTool import ShellTool

        toolComp = self._agent.GetComponent(_TC)
        shellTool = toolComp.Get("shell")
        if shellTool is None or not isinstance(shellTool, ShellTool):
            return ToolResult.Fail(
                "ShellTool not available on current agent",
                toolName=self.name,
            )

        proc = shellTool.GetBackgroundProcess(terminal_id)
        if proc is None:
            return ToolResult.Fail(
                f"Unknown terminal_id: '{terminal_id}'. "
                "It may have already been collected or never existed.",
                toolName=self.name,
            )

        command = shellTool.GetBackgroundCommand(terminal_id)

        try:
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(), timeout=wait_seconds
            )
        except asyncio.TimeoutError:
            return ToolResult.Ok(
                f"[Command still running (terminal_id: {terminal_id})]\n"
                f"Command: {command}\n"
                f"Check again with GetTerminalOutput to get results when complete.",
                toolName=self.name,
            )

        shellTool.RemoveBackgroundProcess(terminal_id)

        output = (stdout or b"").decode("utf-8", errors="replace")
        errorOutput = (stderr or b"").decode("utf-8", errors="replace")

        parts: list[str] = []
        if output:
            if len(output) > MAX_OUTPUT_LENGTH:
                output = output[:MAX_OUTPUT_LENGTH] + "\n... (output truncated)"
            parts.append(output)
        if errorOutput:
            if len(errorOutput) > MAX_OUTPUT_LENGTH:
                errorOutput = errorOutput[:MAX_OUTPUT_LENGTH] + "\n... (stderr truncated)"
            parts.append(f"[stderr]\n{errorOutput}")

        resultText = "\n".join(parts) if parts else "(no output)"
        resultText = (
            f"[Exit code: {proc.returncode}] (terminal_id: {terminal_id})\n"
            f"Command: {command}\n"
            f"{resultText}"
        )

        return ToolResult.Ok(resultText, toolName=self.name)
