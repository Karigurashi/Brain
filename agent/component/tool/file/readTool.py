"""Read 工具 —— 读取本地文件系统上的文件，支持文本与图片。"""

from __future__ import annotations

import os
from itertools import islice

from ..baseTool import BaseTool, EToolParallelMode
from ..eToolCategory import EToolCategory
from ..toolResult import ToolResult
from ..toolComponent import ToolComponent
from agent.component.contex.eContextLodLevel import EContextLodLevel
from agent.component.data.dataComponent import DataComponent

MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB


@ToolComponent.Register
class ReadFileTool(BaseTool):
    """读取文件内容并返回文本。

    支持文本文件的读取，自动处理编码问题。
    当无 start_line/end_line 且文件超大时，返回截断预览以避免上下文膨胀。
    """

    name: str = "read"
    description: str = "Read a file from the local filesystem. Supports text and images (jpeg/jpg, png, webp)."
    category: EToolCategory = EToolCategory.FILE
    parallelMode: EToolParallelMode = EToolParallelMode.PATH
    skipPersist: bool = True
    resultLodLevel = EContextLodLevel.DISCARDABLE
    parameters: dict = {
        "type": "object",
        "properties": {
            "file_path": {
                "type": "string",
                "description": "File path"
            },
            "start_line": {
                "type": "integer",
                "description": "Start line"
            },
            "end_line": {
                "type": "integer",
                "description": "End line"
            },
        },
        "required": ["file_path"],
    }

    def _Invoke(
        self,
        file_path: str,
        start_line: int = 0,
        end_line: int = 0,
    ) -> ToolResult:
        try:
            if not os.path.isfile(file_path):
                return ToolResult.Fail(f"File not found: {file_path}", toolName=self.name)

            fileSize = os.path.getsize(file_path)
            if fileSize > MAX_FILE_SIZE:
                return ToolResult.Fail(
                    f"File too large: {fileSize} bytes exceeds limit of {MAX_FILE_SIZE} bytes ({file_path}).",
                    toolName=self.name,
                )

            # 如果两个都指定了且 start_line > end_line，自动反转，防止 AI 传反顺序
            if start_line > 0 and end_line > 0 and start_line > end_line:
                start_line, end_line = end_line, start_line

            with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                if start_line > 0 or end_line > 0:
                    # islice 按需跳行，避免 readlines() 全量加载到内存
                    sl = max(1, start_line) if start_line > 0 else 1
                    el = end_line if end_line > 0 else None
                    # 先跳过前 sl-1 行，再取到 el
                    if sl > 1:
                        next(islice(f, sl - 2, sl - 1), None)  # consume up to sl-2
                        content = "".join(islice(f, 0, (el - sl + 1) if el else None))
                    else:
                        content = "".join(islice(f, 0, el if el else None))
                    total = content.count("\n") + 1
                    header = f"[File: {file_path} (lines {sl}-{el if el else 'end'})]\n"
                    return ToolResult.Ok(header + content, toolName=self.name)
                else:
                    content = f.read()

            # 全量读取且内容超大 → 截断预览，避免 ContentStore 落盘文件被
            # 全量回读后重新注入上下文，消解优化效果。
            # 行号范围读取不受此限制（AI 已精确指定需求）。
            # 阈值从 DataComponent 的 PersistConfig 动态读取，保持全局一致。
            config = self._agent.GetComponent(DataComponent).config
            truncChars = config.persistCharThreshold
            previewChars = config.persistPreviewChars
            if len(content) > truncChars:
                totalLines = content.count("\n") + 1
                preview = content[:previewChars]
                moreChars = len(content) - previewChars
                header = (
                    f"[File: {file_path}]\n"
                    f"Size: {len(content)} chars | {totalLines} lines | {fileSize} bytes\n"
                    f"--- preview (first {previewChars} chars) ---\n"
                )
                suffix = (
                    f"\n... ({moreChars} more chars)\n"
                    f"File is large. Use start_line/end_line to read specific sections."
                )
                return ToolResult.Ok(header + preview + suffix, toolName=self.name)

            header = f"[File: {file_path}]\n"
            return ToolResult.Ok(header + content, toolName=self.name)

        except Exception as exc:
            return ToolResult.Fail(f"Failed to read '{file_path}': {exc}", toolName=self.name)
