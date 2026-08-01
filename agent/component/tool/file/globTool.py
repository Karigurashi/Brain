"""Glob 工具 —— 按 glob 模式搜索文件（ripgrep 硬依赖）。

通过 rg --files 子进程执行搜索（原生支持 .gitignore、.mangoIgnore、并行目录遍历）。
rg 未安装时直接返回安装提示，不提供 Python 回退。
"""

from __future__ import annotations

import os
from pathlib import Path

from ..baseTool import BaseTool, EToolParallelMode
from ..eToolCategory import EToolCategory
from ..toolResult import ToolResult
from ..toolComponent import ToolComponent
from agent.component.contex.eContextLodLevel import EContextLodLevel
from agent.core.fileUtils import FileUtils

MAX_RESULTS = 500


@ToolComponent.Register
class SearchFileTool(BaseTool):
    """按 glob 模式搜索文件，只返回匹配文件的路径。限制最多 500 个结果。

    依赖 ripgrep 子进程，未安装时返回安装提示。
    """

    name: str = "glob"
    description: str = "Search files by glob pattern. Returns matching paths. Limited to 500 results"
    category: EToolCategory = EToolCategory.FILE
    timeout: float = 15.0
    parallelMode: EToolParallelMode = EToolParallelMode.SAFE
    resultLodLevel = EContextLodLevel.DISCARDABLE
    parameters: dict = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Glob pattern, MUST be relative. e.g. *.go, **/test/*.py",
            },
            "path": {
                "type": "string",
                "description": "Search directory (supports absolute paths). Defaults to workspace root",
            },
        },
        "required": ["query"],
    }

    def _Invoke(self, query: str, path: str = ".") -> ToolResult:
        try:
            rootPath = Path(path)
            if not rootPath.is_dir():
                return ToolResult.Fail(f"Not a directory: {path}", toolName=self.name)
            if not FileUtils.DetectRg():
                return ToolResult.Fail(FileUtils.RG_NOT_FOUND_MSG, toolName=self.name)

            return self._InvokeWithRipgrep(query, rootPath)

        except Exception as exc:
            return ToolResult.Fail(f"Search failed: {exc}", toolName=self.name)

    def _InvokeWithRipgrep(self, query: str, rootPath: Path) -> ToolResult:
        """rg --files + glob 过滤 + .mangoIgnore。

        rglob 语义对齐：无斜杠模式匹配任意层级 basename（rg 的 gitignore 语义天然一致）；
        含斜杠且未以 **/ 开头的模式补 **/ 前缀（rg 中含斜杠模式默认锚定根目录）。
        """
        rgPattern = query if query.startswith("**/") or "/" not in query else f"**/{query}"
        globFlag = "--iglob" if os.name == "nt" else "-g"

        cmd: list[str] = ["rg", "--no-config", "--files", globFlag, rgPattern]
        FileUtils.AppendIgnoreFileArg(cmd)
        cmd.append(str(rootPath))

        # 子进程超时与工具 timeout（15s）对齐
        stdout, err = FileUtils.RunRg(cmd, timeout=15)
        if stdout is None:
            return ToolResult.Fail(f"ripgrep failed: {err}", toolName=self.name)

        rootStr = str(rootPath)
        results: list[str] = []
        seen: set[str] = set()
        for line in stdout.splitlines():
            filePath = line.strip()
            if not filePath:
                continue
            rel = os.path.relpath(filePath, rootStr).replace("\\", "/")
            if rel not in seen:
                seen.add(rel)
                results.append(rel)
            if len(results) >= MAX_RESULTS:
                break

        return self._BuildResult(query, rootStr, results)

    def _BuildResult(self, query: str, rootStr: str, results: list[str]) -> ToolResult:
        if not results:
            return ToolResult.Ok(
                f"No files matching '{query}' found in '{rootStr}'.",
                toolName=self.name,
            )

        content = f"[Files matching '{query}' in '{rootStr}' ({len(results)} results)]\n"
        content += "\n".join(f"  {r}" for r in results)
        if len(results) >= MAX_RESULTS:
            content += f"\n... (truncated at {MAX_RESULTS} results)"
        return ToolResult.Ok(content, toolName=self.name)
