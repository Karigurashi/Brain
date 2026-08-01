"""Grep 工具 —— 高性能文件内容搜索（ripgrep 硬依赖）。

通过 rg 子进程执行搜索（原生支持 .gitignore、.mangoIgnore、并行搜索、mmap）。
rg 未安装时直接返回安装提示，不提供 Python 回退。

支持三种模式：
1. 正则行级搜索（默认）：返回匹配行 + 上下文。
2. keywords 文件级 AND（原 searchCodebase 能力）：文件须同时包含全部关键词，
   返回候选文件 + 每文件前若干行命中预览。
3. filesOnly：仅返回命中文件路径列表。
"""

from __future__ import annotations

import os
import re
from typing import Any

from ..baseTool import BaseTool, EToolParallelMode
from ..eToolCategory import EToolCategory
from ..toolResult import ToolResult
from ..toolComponent import ToolComponent
from agent.component.contex.eContextLodLevel import EContextLodLevel
from agent.core.fileUtils import FileUtils

MAX_RESULTS = 500
MAX_LINE_LENGTH = 500
MAX_OUTPUT_LINES = 2000  # 行级搜索全局输出行数上限（rg --max-count 为每文件限制，需解析层兜底）
CONTEXT_LINES = 2
MAX_FILES = 200  # keywords 模式候选文件上限
PREVIEW_FILES = 50  # keywords 模式提供行预览的文件数上限
PREVIEW_LINES = 5  # keywords 模式每文件预览行数

_RG_MATCH_SEP = ":"
_RG_CONTEXT_SEP = "-"


@ToolComponent.Register
class GrepCodeTool(BaseTool):
    """高性能文件内容搜索，支持正则表达式。结果自动展开为完整语法块。

    依赖 ripgrep 子进程，未安装时返回安装提示。
    """

    name: str = "grep"
    description: str = "Search file contents by regex. Supports keyword AND, paths-only mode."
    category: EToolCategory = EToolCategory.FILE
    timeout: float = 30.0
    parallelMode: EToolParallelMode = EToolParallelMode.SAFE
    resultLodLevel = EContextLodLevel.DISCARDABLE
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "regex": {
                "type": "string",
                "description": "Regex pattern"
            },
            "path": {
                "type": "string",
                "description": "Target file or directory"
            },
            "type": {
                "type": "string",
                "description": "File type filter, e.g. js, py, rust"
            },
            "glob": {
                "type": "string",
                "description": "File glob filter"
            },
            "caseInsensitive": {
                "type": "boolean",
                "description": "Case-insensitive"
            },
            "contextAfter": {
                "type": "number",
                "description": "Lines after match"
            },
            "contextBefore": {
                "type": "number",
                "description": "Lines before match"
            },
            "contextAround": {
                "type": "number",
                "description": "Lines before and after match"
            },
            "multiline": {
                "type": "boolean",
                "description": "Multiline matching"
            },
            "filesOnly": {
                "type": "boolean",
                "description": "Return file paths only"
            },
            "keywords": {
                "type": "string",
                "description": "Comma-separated AND keywords; overrides regex"
            },
        },
        "required": ["regex"],
    }

    @staticmethod
    def _SanitizeRegex(regex: str) -> str:
        """将 \\uXXXX 转义序列还原为实际 Unicode 字符。

        避免 AI 生成的 UTF-16 代理对（如 \\ud83d）直接传给 ripgrep 导致
        'hexadecimal literal is not a Unicode scalar value' 错误。
        高位代理与低位代理配对后还原为增补平面字符，孤立代理丢弃。
        """
        _highSurrogate: int | None = None

        def _ReplaceUnicodeEscape(m: re.Match[str]) -> str:
            nonlocal _highSurrogate
            code = int(m.group(1), 16)
            if 0xD800 <= code <= 0xDBFF:   # 高位代理，缓存等待配对
                _highSurrogate = code
                return ""
            if 0xDC00 <= code <= 0xDFFF:   # 低位代理，与缓存配对
                if _highSurrogate is not None:
                    high = _highSurrogate
                    _highSurrogate = None
                    charCode = 0x10000 + (high - 0xD800) * 0x400 + (code - 0xDC00)
                    return chr(charCode)
                return ""  # 孤立低位代理，丢弃
            # 普通 BMP 字符
            return chr(code)

        return re.sub(r"\\u([0-9a-fA-F]{4})", _ReplaceUnicodeEscape, regex)

    def _Invoke(
        self,
        regex: str,
        path: str = ".",
        type: str = "",
        glob: str = "",
        caseInsensitive: bool = False,
        contextAfter: int = 0,
        contextBefore: int = 0,
        contextAround: int = 0,
        multiline: bool = False,
        filesOnly: bool = False,
        keywords: str = "",
    ) -> ToolResult:
        try:
            regex = self._SanitizeRegex(regex)
            if not os.path.exists(path):
                return ToolResult.Fail(f"Path not found: {path}", toolName=self.name)
            if not FileUtils.DetectRg():
                return ToolResult.Fail(FileUtils.RG_NOT_FOUND_MSG, toolName=self.name)

            kwList = [kw.strip() for kw in keywords.split(",") if kw.strip()]
            if kwList:
                return self._InvokeKeywords(kwList, os.path.abspath(path), type, glob, caseInsensitive)
            if filesOnly:
                return self._InvokeFilesOnly(regex, os.path.abspath(path), type, glob, caseInsensitive)

            if contextAround:
                if not contextBefore:
                    contextBefore = contextAround
                if not contextAfter:
                    contextAfter = contextAround
            if not contextBefore and not contextAfter:
                contextBefore = CONTEXT_LINES
                contextAfter = CONTEXT_LINES

            if os.path.isfile(path):
                return self._InvokeOnSingleFile(
                    regex, path, caseInsensitive, contextAfter, contextBefore, multiline,
                )
            if not os.path.isdir(path):
                return ToolResult.Fail(f"Not a file or directory: {path}", toolName=self.name)

            return self._InvokeWithRipgrep(
                regex, path, type, glob,
                caseInsensitive, contextAfter, contextBefore, multiline,
            )

        except Exception as exc:
            return ToolResult.Fail(f"Grep failed: {exc}", toolName=self.name)

    # ---- 公共助手 ----

    @staticmethod
    def _BuildRgFilterArgs(fileType: str, globPattern: str) -> list[str]:
        """构建 rg 的文件类型/glob 过滤参数。"""
        args: list[str] = []
        for ft in fileType.split(","):
            ft = ft.strip()
            if ft:
                args.extend(["-t", ft])
        if globPattern:
            args.extend(["-g", globPattern])
        return args

    @staticmethod
    def _RootDirOf(searchPath: str) -> str:
        if os.path.isdir(searchPath):
            return searchPath
        return os.path.dirname(searchPath) or "."

    # ---- keywords 文件级 AND 模式 ----

    def _InvokeKeywords(
        self,
        keywords: list[str],
        searchPath: str,
        fileType: str,
        globPattern: str,
        caseInsensitive: bool,
    ) -> ToolResult:
        """文件级 AND：各关键词命中文件集合求交集。"""
        noMatch = ToolResult.Ok(
            f"No files found matching keywords: {', '.join(keywords)}",
            toolName=self.name,
        )

        fileLists: list[list[str]] = []
        for kw in keywords:
            cmd: list[str] = ["rg", "--no-config", "--files-with-matches", "-F"]
            if caseInsensitive:
                cmd.append("-i")
            cmd.extend(self._BuildRgFilterArgs(fileType, globPattern))
            FileUtils.AppendIgnoreFileArg(cmd)
            cmd.extend(["-e", kw, searchPath])

            stdout, err = FileUtils.RunRg(cmd, timeout=30)
            if stdout is None:
                return ToolResult.Fail(f"ripgrep failed: {err}", toolName=self.name)
            files = [ln.strip() for ln in stdout.splitlines() if ln.strip()]
            if not files:
                return noMatch
            fileLists.append(files)

        common = set(fileLists[0])
        for files in fileLists[1:]:
            common &= set(files)
        matchedFiles = [f for f in fileLists[0] if f in common][:MAX_FILES]
        if not matchedFiles:
            return noMatch

        rootDir = self._RootDirOf(searchPath)
        previews = self._CollectKeywordPreviews(keywords, matchedFiles[:PREVIEW_FILES], caseInsensitive)

        lines: list[str] = []
        for filePath in matchedFiles:
            lines.append(f"\n[{os.path.relpath(filePath, rootDir)}]")
            for lineNum, text in previews.get(os.path.normpath(filePath), []):
                lines.append(f"  {lineNum:>6}: {text[:MAX_LINE_LENGTH]}")
        if len(matchedFiles) > PREVIEW_FILES:
            lines.append(f"\n... ({len(matchedFiles) - PREVIEW_FILES} more files, paths listed only)")

        header = (
            f"[Keywords AND results for '{', '.join(keywords)}' in '{searchPath}' "
            f"({len(matchedFiles)} files)]"
        )
        return ToolResult.Ok(header + "\n".join(lines), toolName=self.name)

    def _CollectKeywordPreviews(
        self,
        keywords: list[str],
        files: list[str],
        caseInsensitive: bool,
    ) -> dict[str, list[tuple[int, str]]]:
        """单次 rg 调用抓取每个文件前 PREVIEW_LINES 行命中预览（关键词 OR）。失败时降级为空预览。"""
        previews: dict[str, list[tuple[int, str]]] = {}
        if not files:
            return previews

        cmd: list[str] = ["rg", "--no-config", "-n", "-H", "-F", "--color", "never", "--max-count", str(PREVIEW_LINES)]
        if caseInsensitive:
            cmd.append("-i")
        for kw in keywords:
            cmd.extend(["-e", kw])
        cmd.append("--")
        cmd.extend(files)

        stdout, _ = FileUtils.RunRg(cmd, timeout=30)
        if stdout is None:
            return previews

        for line in stdout.splitlines():
            match = re.match(r"^(.+?):(\d+):(.*)$", line)
            if not match:
                continue
            key = os.path.normpath(match.group(1))
            previews.setdefault(key, []).append((int(match.group(2)), match.group(3)))
        return previews

    # ---- filesOnly 模式 ----

    def _InvokeFilesOnly(
        self,
        regex: str,
        searchPath: str,
        fileType: str,
        globPattern: str,
        caseInsensitive: bool,
    ) -> ToolResult:
        cmd: list[str] = ["rg", "--no-config", "--files-with-matches"]
        if caseInsensitive:
            cmd.append("-i")
        cmd.extend(self._BuildRgFilterArgs(fileType, globPattern))
        FileUtils.AppendIgnoreFileArg(cmd)
        cmd.extend(["-e", regex, searchPath])

        stdout, err = FileUtils.RunRg(cmd, timeout=30)
        if stdout is None:
            return ToolResult.Fail(f"ripgrep failed: {err}", toolName=self.name)

        files = [ln.strip() for ln in stdout.splitlines() if ln.strip()][:MAX_RESULTS]
        if not files:
            return ToolResult.Ok(
                f"No files found matching regex '{regex}' in '{searchPath}'.",
                toolName=self.name,
            )

        rootDir = self._RootDirOf(searchPath)
        lines = [f"  {os.path.relpath(f, rootDir)}" for f in files]
        header = f"[Files matching '{regex}' in '{searchPath}' ({len(files)} files)]"
        return ToolResult.Ok(header + "\n" + "\n".join(lines), toolName=self.name)

    # ---- 正则行级搜索模式 ----

    @staticmethod
    def _IsMultilineSuggestError(err: str) -> bool:
        """rg 报错是否建议启用 multiline 模式（如 literal '\n' not allowed）。"""
        return "not allowed in a regex" in err or "multiline" in err.lower()

    def _InvokeWithRipgrep(
        self,
        regex: str,
        rootDir: str,
        fileType: str,
        globPattern: str,
        caseInsensitive: bool,
        contextAfter: int,
        contextBefore: int,
        multiline: bool,
    ) -> ToolResult:
        """目录级 rg 行级搜索。rg 报 multiline 相关错误时自动重试 -U 模式。"""
        cmd: list[str] = ["rg", "--no-config", "-n", "--color", "never"]

        if contextBefore > 0:
            cmd.extend(["-B", str(contextBefore)])
        if contextAfter > 0:
            cmd.extend(["-A", str(contextAfter)])
        if caseInsensitive:
            cmd.append("-i")
        if multiline:
            cmd.append("-U")

        cmd.extend(self._BuildRgFilterArgs(fileType, globPattern))
        FileUtils.AppendIgnoreFileArg(cmd)

        cmd.extend(["--max-count", str(MAX_RESULTS)])
        cmd.extend([regex, rootDir])

        stdout, err = FileUtils.RunRg(cmd, timeout=30)
        if stdout is None:
            if not multiline and self._IsMultilineSuggestError(err):
                return self._InvokeWithRipgrep(
                    regex, rootDir, fileType, globPattern,
                    caseInsensitive, contextAfter, contextBefore, True,
                )
            return ToolResult.Fail(f"ripgrep failed: {err}", toolName=self.name)
        if not stdout.strip():
            return ToolResult.Ok(
                f"No matches found for regex '{regex}' in '{rootDir}'.",
                toolName=self.name,
            )

        return self._ParseRipgrepOutput(regex, rootDir, stdout, fileType)

    def _ParseRipgrepOutput(
        self,
        regex: str,
        rootDir: str,
        output: str,
        fileType: str,
    ) -> ToolResult:
        """解析 rg 标准文本输出为格式化结果。全局输出超 MAX_OUTPUT_LINES 时截断。"""
        results: list[str] = []
        matchCount = 0
        currentRelPath = ""
        fileResults: list[str] = []
        truncated = False

        for line in output.splitlines():
            if not line:
                continue
            if len(results) + len(fileResults) >= MAX_OUTPUT_LINES:
                truncated = True
                break

            match = re.match(r"^(.+?)([-:])(\d+)([-:])(.*)$", line)
            if match:
                filePath = match.group(1)
                lineNum = int(match.group(3))
                isMatch = match.group(4) == _RG_MATCH_SEP
                content = match.group(5)

                relPath = os.path.relpath(filePath, rootDir)
                if relPath != currentRelPath:
                    if fileResults:
                        results.extend(fileResults)
                        fileResults.clear()
                    currentRelPath = relPath
                    fileResults.append(f"\n[{relPath}]")

                marker = ">" if isMatch else " "
                truncated = content[:MAX_LINE_LENGTH]
                fileResults.append(f"  {marker} {lineNum:>6}: {truncated}")
                if isMatch:
                    matchCount += 1
            else:
                fileResults.append(f"  {line[:MAX_LINE_LENGTH]}")

        # 截断时亦保留残块：否则首个文件块内截断会导致 results 为空，误判为无匹配
        if fileResults:
            results.extend(fileResults)

        if not results:
            return ToolResult.Ok(
                f"No matches found for regex '{regex}' in '{rootDir}'.",
                toolName=self.name,
            )

        header = f"[Grep results for '{regex}' in '{rootDir}' ({matchCount} matches"
        if fileType:
            header += f", types: {fileType}"
        if truncated:
            header += f", TRUNCATED at {MAX_OUTPUT_LINES} lines - refine regex"
        header += "]"

        return ToolResult.Ok(header + "\n".join(results), toolName=self.name)

    def _InvokeOnSingleFile(
        self,
        regex: str,
        filePath: str,
        caseInsensitive: bool,
        contextAfter: int,
        contextBefore: int,
        multiline: bool,
    ) -> ToolResult:
        """对单个文件执行 rg 行级搜索。rg 报 multiline 相关错误时自动重试 -U 模式。"""
        cmd: list[str] = ["rg", "--no-config", "-n", "-H", "--color", "never"]
        if contextBefore > 0:
            cmd.extend(["-B", str(contextBefore)])
        if contextAfter > 0:
            cmd.extend(["-A", str(contextAfter)])
        if caseInsensitive:
            cmd.append("-i")
        if multiline:
            cmd.append("-U")
        cmd.extend(["--max-count", str(MAX_RESULTS)])
        cmd.extend([regex, filePath])

        stdout, err = FileUtils.RunRg(cmd, timeout=30)
        if stdout is None:
            if not multiline and self._IsMultilineSuggestError(err):
                return self._InvokeOnSingleFile(
                    regex, filePath,
                    caseInsensitive, contextAfter, contextBefore, True,
                )
            return ToolResult.Fail(f"ripgrep failed: {err}", toolName=self.name)
        if not stdout.strip():
            return ToolResult.Ok(
                f"No matches found for regex '{regex}' in '{filePath}'.",
                toolName=self.name,
            )

        return self._ParseRipgrepOutput(regex, os.path.dirname(filePath) or ".", stdout, "")
