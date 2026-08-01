"""SearchReplace 工具 —— 在文件中进行精确字符串替换。"""

from __future__ import annotations

import os

from ..baseTool import BaseTool, EToolParallelMode
from ..eToolCategory import EToolCategory
from ..toolResult import ToolResult
from ..toolComponent import ToolComponent


@ToolComponent.Register
class SearchReplaceTool(BaseTool):
    """在文件中进行精确字符串替换。支持一次调用中进行多个替换操作。

    每次替换的 original_text 在文件内必须唯一（replace_all=False）或至少出现一次（replace_all=True）。
    替换按传入顺序依次执行。
    """

    name: str = "searchReplace"
    description: str = "Exact string replacements in a file. Supports multiple ops in one call."
    category: EToolCategory = EToolCategory.FILE
    parallelMode: EToolParallelMode = EToolParallelMode.PATH
    parameters: dict = {
        "type": "object",
        "properties": {
            "file_path": {
                "type": "string",
                "description": "Target file absolute path. Must exist"
            },
            "replacements": {
                "type": "array",
                "description": "Replacement operations",
                "items": {
                    "type": "object",
                    "properties": {
                        "original_text": {
                            "type": "string",
                            "description": "Text to replace"
                        },
                        "new_text": {
                            "type": "string",
                            "description": "Replacement text"
                        },
                        "replace_all": {
                            "type": "boolean",
                            "description": "Replace all occurrences"
                        },
                    },
                    "required": ["original_text", "new_text"],
                },
            },
        },
        "required": ["file_path", "replacements"],
    }

    def _Invoke(self, file_path: str, replacements: list[dict]) -> ToolResult:
        try:
            if not os.path.isfile(file_path):
                return ToolResult.Fail(f"File not found: {file_path}", toolName=self.name)

            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()

            modified = content
            appliedCount = 0
            reportLines: list[str] = []

            for i, rep in enumerate(replacements):
                if not isinstance(rep, dict):
                    return ToolResult.Fail(
                        f"replacements[{i}] must be an object", toolName=self.name
                    )
                # 兼容常见别名：old_str / old_text → original_text, new_str → new_text
                original = rep.get("original_text") or rep.get("old_str") or rep.get("old_text") or ""
                newText = rep.get("new_text") or rep.get("new_str") or ""
                replaceAll = rep.get("replace_all", False)

                if not original:
                    return ToolResult.Fail(
                        f"replacements[{i}].original_text must be a non-empty string",
                        toolName=self.name,
                    )
                if original == newText:
                    return ToolResult.Fail(
                        f"replacements[{i}]: original_text and new_text must be different",
                        toolName=self.name,
                    )

                count = modified.count(original)

                if count == 0:
                    return ToolResult.Fail(
                        f"replacements[{i}]: original_text not found in file. "
                        f"Preview: '{original[:120]}{'...' if len(original) > 120 else ''}'",
                        toolName=self.name,
                    )

                if not replaceAll and count > 1:
                    return ToolResult.Fail(
                        f"replacements[{i}]: original_text matches {count} locations but replace_all is false. "
                        f"Provide more context to make it unique, or set replace_all=true. "
                        f"Preview: '{original[:120]}{'...' if len(original) > 120 else ''}'",
                        toolName=self.name,
                    )

                modified = modified.replace(original, newText) if replaceAll else modified.replace(original, newText, 1)
                appliedCount += 1
                reportLines.append(
                    f"  [{i + 1}] {'ALL' if replaceAll else '1'} occurrence(s) replaced"
                )

            with open(file_path, "w", encoding="utf-8") as f:
                f.write(modified)

            summary = (
                f"Successfully applied {appliedCount} replacement(s) to '{file_path}':\n"
                + "\n".join(reportLines)
            )
            return ToolResult.Ok(summary, toolName=self.name)

        except PermissionError:
            return ToolResult.Fail(f"Permission denied: {file_path}", toolName=self.name)
        except Exception as exc:
            return ToolResult.Fail(
                f"SearchReplace failed on '{file_path}': {exc}", toolName=self.name
            )
