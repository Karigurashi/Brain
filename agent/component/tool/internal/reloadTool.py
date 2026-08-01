"""Reload 工具 —— 重建 harness，热重载 rules / skills / MCP 工具。

对标 Channel 内置指令 /reload：安装 skill、MCP 或更新 rule 后，
由 LLM 主动调用以使变更立即生效。
"""

from __future__ import annotations

from agent.component.contex.eContextLodLevel import EContextLodLevel
from agent.component.harness import HarnessComponent

from ..baseTool import BaseTool, EToolParallelMode
from ..eToolCategory import EToolCategory
from ..toolResult import ToolResult
from ..toolComponent import ToolComponent


@ToolComponent.Register
class ReloadTool(BaseTool):
    """重建 harness：重载 rules / skills / MCP 工具配置并重新绑定到 LLM。

    在安装 skill、配置 MCP 或更新 rule 后调用，无需等待用户执行 /reload。
    """

    name: str = "reload"
    description: str = "Reload rules/skills/MCP after install or update"
    category: EToolCategory = EToolCategory.INTERNAL
    parallelMode: EToolParallelMode = EToolParallelMode.SERIAL
    resultLodLevel = EContextLodLevel.DISCARDABLE
    parameters: dict = {
        "type": "object",
        "properties": {},
        "required": [],
    }

    async def _InvokeAsync(self) -> ToolResult:
        harness = self._agent.GetComponent(HarnessComponent)
        await harness.BuildAsync(force=True)
        toolCount = self._agent.GetComponent(ToolComponent).Count()
        return ToolResult.Ok(
            f"Reloaded ({toolCount} tools registered).",
            toolName=self.name,
        )
