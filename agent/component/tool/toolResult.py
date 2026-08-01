"""工具执行结果 —— 统一的不可变工具返回值封装。

使用 frozen dataclass + __slots__ 确保不可变性与低内存开销，
适用于只追加不修改的 Agent 会话事件流。
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any


@dataclass(slots=True, frozen=True)
class ToolResult:
    """工具执行结果，被 Agent 消费用于下一步决策。

    不可变（frozen dataclass + __slots__）：适合 Agent 事件流的追加模式。

    Attributes:
        success: 执行是否成功。
        content: 结果文本内容（注入 LLM context）。
        data: 结构化数据（可选，程序化消费）。
        error: 错误信息（success=False 时填充）。
        toolName: 来源工具名称。
        roleMessage: 工具执行后额外注入的 user 消息内容。
            非空时由框架在 tool_result 之前以 USER 角色注入。
            对标 Claude Code Skill 工具的 newMessages 机制。
    """

    success: bool
    content: str = ""
    data: Any = None
    error: str = ""
    toolName: str = ""
    roleMessage: str = ""

    @staticmethod
    def Ok(
        content: str,
        data: Any = None,
        toolName: str = "",
        roleMessage: str = "",
    ) -> "ToolResult":
        """快捷构造成功结果。"""
        return ToolResult(
            success=True,
            content=content,
            data=data,
            toolName=toolName,
            roleMessage=roleMessage,
        )

    @staticmethod
    def Fail(error: str, toolName: str = "") -> "ToolResult":
        """快捷构造失败结果。"""
        return ToolResult(success=False, content=error, error=error, toolName=toolName)

    @property
    def isEmpty(self) -> bool:
        """结果是否为空。"""
        return not self.content and self.data is None

    def ToLLMContent(self) -> str:
        """转为注入 LLM context 的文本格式。"""
        if self.success:
            return self.content
        return f"Error ({self.toolName}): {self.error}"

    def WithToolName(self, toolName: str) -> "ToolResult":
        """返回一个设置 toolName 的新实例（不可变替换）。"""
        return replace(self, toolName=toolName)
