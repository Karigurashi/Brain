"""Write 工具 —— 创建新文件或修改现有文件。"""

from __future__ import annotations

import os

from ..baseTool import BaseTool, EToolParallelMode
from ..eToolCategory import EToolCategory
from ..toolResult import ToolResult
from ..toolComponent import ToolComponent


@ToolComponent.Register
class WriteFileTool(BaseTool):
    """创建新文件或修改现有文件。

    文件内容限制最多 1000 行。支持分部分写入（append 模式）。
    """

    name: str = "write"
    description: str = "Create or overwrite a file. Max 1000 lines. Supports append mode."
    category: EToolCategory = EToolCategory.FILE
    parallelMode: EToolParallelMode = EToolParallelMode.PATH
    parameters: dict = {
        "type": "object",
        "properties": {
            "file_path": {
                "type": "string",
                "description": "Absolute path"
            },
            "file_content": {
                "type": "string",
                "description": "File content"
            },
            "add_last_line_newline": {
                "type": "boolean",
                "description": "Add trailing newline"
            },
            "append": {
                "type": "boolean",
                "description": "Append mode"
            },
            "continuation_context": {
                "type": "string",
                "description": "Last 3 lines of previous write"
            },
        },
        "required": ["file_path", "file_content"],
    }

    def _Invoke(
        self,
        file_path: str,
        file_content: str = "",
        add_last_line_newline: bool = True,
        append: bool = False,
        continuation_context: str = "",
        **kwargs,
    ) -> ToolResult:
        # 参数别名兼容：LLM 常将 file_content 误写为 content
        if not file_content:
            file_content = kwargs.pop("content", "")
        try:
            # ---- 追加模式下的衔接校验 ----
            if append and continuation_context:
                if os.path.isfile(file_path):
                    ctxLines = continuation_context.strip("\n").split("\n")
                    tailLines = len(ctxLines)
                    # 仅读文件尾部 ~8KB 校验，避免大文件全量读取
                    with open(file_path, "rb") as f:
                        f.seek(0, 2)  # end of file
                        fileSize = f.tell()
                        readSize = min(fileSize, 8192)
                        f.seek(-readSize, 2)
                        tailBytes = f.read(readSize)
                    tailText = tailBytes.decode("utf-8", errors="replace")
                    existingTail = "\n".join(tailText.split("\n")[-tailLines:])
                    expectedTail = "\n".join(ctxLines)
                    if existingTail != expectedTail:
                        return ToolResult.Fail(
                            f"Continuation context mismatch: the end of '{file_path}' "
                            f"does not match the provided continuation_context. "
                            f"The file may have been modified since the last write.",
                            toolName=self.name,
                        )
                else:
                    return ToolResult.Fail(
                        f"Cannot append with continuation_context: file '{file_path}' does not exist.",
                        toolName=self.name,
                    )

            # ---- 尾部换行处理 ----
            finalContent = file_content
            if add_last_line_newline and finalContent and not finalContent.endswith("\n"):
                finalContent += "\n"

            # ---- 父目录创建 ----
            parentDir = os.path.dirname(file_path)
            if parentDir:
                os.makedirs(parentDir, exist_ok=True)

            # ---- 写入 ----
            mode = "a" if append else "w"
            with open(file_path, mode, encoding="utf-8") as f:
                f.write(finalContent)

            lineCount = finalContent.count("\n") + (1 if finalContent and not finalContent.endswith("\n") else 0)
            modeLabel = "Appended to" if append else "Wrote"
            return ToolResult.Ok(
                f"{modeLabel} {len(finalContent.encode('utf-8'))} bytes ({lineCount} lines) to '{file_path}'.",
                toolName=self.name,
            )

        except PermissionError:
            return ToolResult.Fail(f"Permission denied: {file_path}", toolName=self.name)
        except Exception as exc:
            return ToolResult.Fail(f"Failed to write '{file_path}': {exc}", toolName=self.name)
