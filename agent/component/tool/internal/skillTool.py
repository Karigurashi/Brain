"""Skill 工具 —— 将 Skill 渐进式披露的 Layer 2 挂载到 ToolComponent。

对标 Claude Code Skill 工具：
- Layer 1: name + description 已通过 ContextAssembler 注入 system prompt。
- Layer 2: 本工具按名加载 Skill 完整 SOP，通过 roleMessage 以 USER 角色
  注入到 tool_result 之前，确保 AI 以指令方式接收。
- Layer 3: referenceFiles 路径在 SOP 正文中引用，后续按需加载标记为
  LOD4(EXTERNAL_ONLY)（当轮注入、次轮丢弃）。
"""

from __future__ import annotations

from agent.component.contex.eContextLodLevel import EContextLodLevel
from agent.component.skill.skillComponent import SkillComponent

from ..baseTool import BaseTool, EToolParallelMode
from ..eToolCategory import EToolCategory
from ..toolResult import ToolResult


class SkillTool(BaseTool):
    """按名称加载 Skill 完整 SOP 正文的工具。

    SOP 正文通过 roleMessage 以 USER 角色注入到 tool_result 之前，
    对标 Claude Code Skill 工具，确保 AI 以指令方式接收。
    """

    name = "skill"
    description = "Load a skill's full instructions by name"
    category = EToolCategory.INTERNAL
    parallelMode = EToolParallelMode.SAFE
    resultLodLevel = EContextLodLevel.SUMMARIZABLE
    parameters = {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "The skill name (no arguments)",
            },
        },
        "required": ["command"],
    }

    def _Invoke(self, command: str) -> ToolResult:
        """加载指定 Skill 的完整 SOP。

        对标 Claude Code Skill 工具：SOP 正文通过 roleMessage 以 USER 角色
        注入到 tool_result 之前，确保 AI 以指令而非参考信息的方式接收。

        Args:
            command: Skill 名称（对应 SKILL.md frontmatter 中的 name 字段）。

        Returns:
            ToolResult: content 为简短确认，roleMessage 为完整 SOP 正文。
        """
        skillComponent = self._agent.GetComponent(SkillComponent)
        content = skillComponent.LoadSkill(command)
        if content.startswith("Error:"):
            return ToolResult.Fail(content, toolName=self.name)
        return ToolResult.Ok(
            f"Skill '{command}' loaded",
            toolName=self.name,
            roleMessage=content,
        )