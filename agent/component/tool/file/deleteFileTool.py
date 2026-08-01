"""DeleteFile 工具 —— 安全删除文件。"""

from __future__ import annotations

import os

from ..baseTool import BaseTool, EToolParallelMode
from ..eToolCategory import EToolCategory
from ..toolResult import ToolResult
from ..toolComponent import ToolComponent


@ToolComponent.Register
class DeleteFileTool(BaseTool):
    """安全删除文件。只能通过此工具删除，不能使用 shell 命令。

    仅删除文件，不删除目录。
    """

    name: str = "deleteFile"
    description: str = "Delete a file. ONLY use this, NOT shell commands"
    category: EToolCategory = EToolCategory.FILE
    parallelMode: EToolParallelMode = EToolParallelMode.PATH
    parameters: dict = {
        "type": "object",
        "properties": {
            "file_path": {
                "type": "string",
                "description": "Absolute path"
            },
        },
        "required": ["file_path"],
    }

    def _Invoke(self, file_path: str) -> ToolResult:
        try:
            if not os.path.exists(file_path):
                return ToolResult.Fail(f"File not found: {file_path}", toolName=self.name)

            if os.path.isdir(file_path):
                return ToolResult.Fail(
                    f"Cannot delete directory: {file_path}. Use shell rm -rf for directories.",
                    toolName=self.name,
                )

            os.remove(file_path)
            return ToolResult.Ok(f"Successfully deleted: {file_path}", toolName=self.name)

        except PermissionError:
            return ToolResult.Fail(f"Permission denied: {file_path}", toolName=self.name)
        except Exception as exc:
            return ToolResult.Fail(f"Failed to delete '{file_path}': {exc}", toolName=self.name)
