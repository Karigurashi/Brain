"""SearchReplace 工具 —— 在文件中进行精确字符串替换。"""

from __future__ import annotations

import difflib
import os

from ..baseTool import BaseTool, EToolParallelMode
from ..eToolCategory import EToolCategory
from ..toolResult import ToolResult
from ..toolComponent import ToolComponent


@ToolComponent.Register
class SearchReplaceTool(BaseTool):
    """在文件中进行精确字符串替换。支持一次调用中进行多个替换操作。

    替换按传入顺序依次执行，前一个替换的结果会影响后续匹配。
    """

    name: str = "searchReplace"
    description: str = "Exact string replacements in a file. Supports multiple sequential ops in one call."
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
                "description": "Replacement operations, applied in order",
                "items": {
                    "type": "object",
                    "properties": {
                        "original_text": {
                            "type": "string",
                            "description": "Exact text to find. Must match precisely including all whitespace, indentation and newlines. Must be unique unless replace_all=true. Include surrounding lines for uniqueness."
                        },
                        "new_text": {
                            "type": "string",
                            "description": "Replacement text. Empty string deletes the match."
                        },
                        "replace_all": {
                            "type": "boolean",
                            "description": "Replace all occurrences. Defaults to false.",
                            "default": False,
                        },
                    },
                    "required": ["original_text", "new_text"],
                },
            },
        },
        "required": ["file_path", "replacements"],
    }

    # ---- 辅助 ----

    @staticmethod
    def _LineNos(content: str, original: str) -> list[int]:
        """返回 original 在 content 中所有出现的起始行号（1-based）。"""
        lineNos: list[int] = []
        start = 0
        while True:
            pos = content.find(original, start)
            if pos == -1:
                break
            lineNos.append(content.count("\n", 0, pos) + 1)
            start = pos + 1
        return lineNos

    @staticmethod
    def _ClosestLine(content: str, original: str) -> str:
        """找文件中与 original 首行最相似的行，返回提示字符串。"""
        target = original.split("\n")[0].strip()
        if not target:
            return ""
        fileLines = content.split("\n")
        close = difflib.get_close_matches(target, fileLines, n=1, cutoff=0.6)
        if not close:
            return ""
        return f" Closest match: line {fileLines.index(close[0]) + 1}: '{close[0][:120]}'"

    # ---- 执行 ----

    def _Invoke(self, file_path: str, replacements: list[dict]) -> ToolResult:
        try:
            if not os.path.isfile(file_path):
                return ToolResult.Fail(f"File not found: {file_path}", toolName=self.name)
            if not replacements:
                return ToolResult.Fail("replacements must be non-empty", toolName=self.name)

            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()

            modified = content
            appliedCount = 0
            reportLines: list[str] = []

            for i, rep in enumerate(replacements):
                if not isinstance(rep, dict):
                    return ToolResult.Fail(f"replacements[{i}] must be an object", toolName=self.name)

                # 显式取值，避免 or 短路导致空字符串被跳过
                original = rep.get("original_text")
                if original is None:
                    original = rep.get("old_str") or rep.get("old_text") or ""
                newText = rep.get("new_text")
                if newText is None:
                    newText = rep.get("new_str") or ""
                replaceAll = rep.get("replace_all", False)

                if not original:
                    return ToolResult.Fail(
                        f"replacements[{i}].original_text must be non-empty", toolName=self.name
                    )
                if original == newText:
                    return ToolResult.Fail(
                        f"replacements[{i}]: original_text and new_text must be different",
                        toolName=self.name,
                    )

                count = modified.count(original)

                if count == 0:
                    hint = self._ClosestLine(modified, original)
                    return ToolResult.Fail(
                        f"replacements[{i}]: original_text not found.{hint} "
                        f"Preview: '{original[:120]}{'...' if len(original) > 120 else ''}'",
                        toolName=self.name,
                    )

                if not replaceAll and count > 1:
                    lineNos = self._LineNos(modified, original)
                    return ToolResult.Fail(
                        f"replacements[{i}]: matches {count} locations (lines {lineNos}), replace_all=false. "
                        f"Add context or set replace_all=true.",
                        toolName=self.name,
                    )

                lineNos = self._LineNos(modified, original)
                modified = modified.replace(original, newText) if replaceAll else modified.replace(original, newText, 1)
                appliedCount += 1
                reportLines.append(f"  [{i + 1}] line {lineNos[0]}{' (all)' if replaceAll else ''}")

            with open(file_path, "w", encoding="utf-8") as f:
                f.write(modified)

            return ToolResult.Ok(
                f"Applied {appliedCount} replacement(s) to '{file_path}':\n" + "\n".join(reportLines),
                toolName=self.name,
            )

        except PermissionError:
            return ToolResult.Fail(f"Permission denied: {file_path}", toolName=self.name)
        except Exception as exc:
            return ToolResult.Fail(f"SearchReplace failed on '{file_path}': {exc}", toolName=self.name)
