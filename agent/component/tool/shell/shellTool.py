"""Shell 工具 —— 在 Windows 终端执行命令。

后台进程管理为实例级，隔离不同 Agent 的后台终端。
"""

from __future__ import annotations

import asyncio
import os
import re
import shlex
import uuid
from typing import Any

from ..baseTool import BaseTool, EToolParallelMode
from ..eToolCategory import EToolCategory
from ..toolResult import ToolResult
from ..toolComponent import ToolComponent
from agent.component.contex.eContextLodLevel import EContextLodLevel

MAX_OUTPUT_LENGTH = 50000

# ---- 安全沙箱常量（Windows 适配） ----

# 允许的安全命令白名单（命令基名）
_DEFAULT_ALLOWED_COMMANDS: set[str] = {
    # 开发工具
    "python", "python3", "node", "npm", "npx", "pnpm", "yarn", "go", "rustc", "cargo",
    "javac", "java", "gcc", "g++", "make", "cmake", "dotnet",
    # 版本控制
    "git", "svn",
    # 包管理
    "pip", "pip3", "conda", "gem",
    # 文件操作（Windows 命令）
    "dir", "type", "more", "findstr", "echo", "sort", "where",
    "xcopy", "robocopy", "comp", "fc",
    # PowerShell cmdlet
    "get-childitem", "get-content", "get-item", "get-location",
    "set-location", "test-path", "resolve-path", "select-string",
    "get-process", "get-service", "get-command", "get-help",
    "write-output", "write-host", "format-list", "format-table",
    # 系统信息
    "whoami", "hostname", "date", "time", "systeminfo", "ver",
    # 构建工具
    "tsc", "esbuild", "webpack", "vite", "rollup",
}

# 危险命令黑名单（Windows）
_DEFAULT_BLOCKED_COMMANDS: set[str] = {
    # 删除
    "del", "remove-item", "rd", "rmdir",
    # 磁盘操作
    "format", "fdisk", "diskpart", "clean",
    # 系统操作
    "shutdown", "restart", "logoff",
    "mkfs", "fsck",
    # 权限操作
    "icacls", "takeown", "runas",
    # 网络危险操作
    "net", "netsh", "ipconfig", "route",
    # 远程操作
    "scp", "sftp", "ssh",
    # 服务管理
    "sc", "reg", "bcdedit",
    # 脚本引擎（可被用于绕过）
    "powershell", "pwsh", "cmd",
    "wscript", "cscript", "mshta",
}

# 危险模式正则（Windows 适配）
_DANGEROUS_PATTERNS: list[re.Pattern] = [
    # 强制删除
    re.compile(r"\bdel\s+/[fq]\b", re.IGNORECASE),
    re.compile(r"\brd\s+/[sq]\b", re.IGNORECASE),
    re.compile(r"\bRemove-Item\b.*-Recurse", re.IGNORECASE),
    # 磁盘操作
    re.compile(r"\bformat\s+[a-zA-Z]:", re.IGNORECASE),
    re.compile(r"\bclean\b", re.IGNORECASE),
    # 注册表操作
    re.compile(r"\breg\s+(add|delete|export)", re.IGNORECASE),
    re.compile(r"\bNew-ItemProperty\b", re.IGNORECASE),
    re.compile(r"\bRemove-ItemProperty\b", re.IGNORECASE),
    # 环境变量注入
    re.compile(r"\$env:", re.IGNORECASE),
    re.compile(r"\bset\s+PATH\s*=", re.IGNORECASE),
    # 权限提升
    re.compile(r"\brunas\b", re.IGNORECASE),
    re.compile(r"\bStart-Process\b.*-Verb\s+RunAs", re.IGNORECASE),
    # 命令替换（PowerShell）
    re.compile(r"\$\("),
    re.compile(r"\$\{"),
    # 管道执行脚本
    re.compile(r"\b(curl|wget|Invoke-WebRequest)\s*.*\|\s*(Invoke-Expression|iex)", re.IGNORECASE),
    re.compile(r"\biex\b", re.IGNORECASE),
    re.compile(r"\bInvoke-Expression\b", re.IGNORECASE),
    # 进程替换
    re.compile(r"<\("),
    re.compile(r">\("),
    # 写入系统路径
    re.compile(r">\s*[A-Z]:\\(Windows|System32|ProgramData)\\", re.IGNORECASE),
]

# Shell 控制操作符，用于将复合命令拆分为独立子命令逐段校验
_SEGMENT_SPLIT_RE = re.compile(r"&&|\|\||[|;&\n]")


@ToolComponent.Register
class ShellTool(BaseTool):
    """在 Windows 终端执行 Shell 命令并捕获输出，含安全沙箱校验。

    安全策略（三级）：
    1. 命令白名单：仅允许 _DEFAULT_ALLOWED_COMMANDS 中的命令。
    2. 命令黑名单：拦截 _DEFAULT_BLOCKED_COMMANDS 中的危险命令。
    3. 模式匹配：正则扫描 _DANGEROUS_PATTERNS，拦截危险操作模式。

    后台进程为实例级管理，隔离不同 Agent 的后台终端。
    """

    name: str = "shell"
    description: str = "Run a Windows shell command. Use for git, npm, etc. NOT file ops"
    category: EToolCategory = EToolCategory.SHELL
    parallelMode: EToolParallelMode = EToolParallelMode.SERIAL
    timeout: float | None = 120.0
    resultLodLevel = EContextLodLevel.DISCARDABLE
    parameters: dict[str, Any] = {
        "type": "object",
        "properties": {
            "command": {
                "type": "string",
                "description": "Shell command to execute"
            },
            "is_background": {
                "type": "boolean",
                "description": "Run in background"
            },
            "timeout": {
                "type": "integer",
                "description": "Timeout in seconds. Default: 120"
            },
        },
        "required": ["command", "is_background"],
    }

    # ---- 安全配置（可按需扩展） ----

    sandboxEnabled: bool = False
    """是否启用安全沙箱，仅在受控环境中可关闭。"""

    allowedCommands: set[str] = _DEFAULT_ALLOWED_COMMANDS.copy()
    """安全命令白名单。"""

    blockedCommands: set[str] = _DEFAULT_BLOCKED_COMMANDS.copy()
    """危险命令黑名单。"""

    dangerousPatterns: list[re.Pattern] = list(_DANGEROUS_PATTERNS)
    """危险模式正则列表。"""

    workingDir: str = ""
    """限制命令执行目录，空字符串表示不限制。"""

    def __init__(self) -> None:
        # 实例级后台进程管理，隔离不同 Agent
        self._backgroundProcesses: dict[str, asyncio.subprocess.Process] = {}
        self._backgroundCommands: dict[str, str] = {}

    # ---- 后台进程访问（供 GetTerminalOutputTool 使用） ----

    def GetBackgroundProcess(self, terminalId: str) -> asyncio.subprocess.Process | None:
        """获取后台进程实例。"""
        return self._backgroundProcesses.get(terminalId)

    def GetBackgroundCommand(self, terminalId: str) -> str:
        """获取后台命令字符串。"""
        return self._backgroundCommands.get(terminalId, "(unknown)")

    def RemoveBackgroundProcess(self, terminalId: str) -> None:
        """从注册表中移除已完成的后台进程。"""
        self._backgroundProcesses.pop(terminalId, None)
        self._backgroundCommands.pop(terminalId, None)

    def CleanupBackgroundProcesses(self) -> None:
        """清理所有后台进程，kill 未完成的进程。"""
        for proc in self._backgroundProcesses.values():
            if proc.returncode is None:
                try:
                    proc.kill()
                except ProcessLookupError:
                    pass
        self._backgroundProcesses.clear()
        self._backgroundCommands.clear()

    def OnDestroy(self) -> None:
        """工具卸载时清理所有后台进程。"""
        self.CleanupBackgroundProcesses()

    # ---- 执行逻辑 ----

    async def _InvokeAsync(
        self,
        command: str,
        is_background: bool = False,
        timeout: int = 120,
    ) -> ToolResult:
        # ---- 安全校验 ----
        if self.sandboxEnabled:
            validationError = self._ValidateCommand(command, allowUnsafe=False)
            if validationError:
                return ToolResult.Fail(
                    f"Command rejected by security sandbox: {validationError}\n"
                    f"Blocked command: {command[:200]}",
                    toolName=self.name,
                )

        # ---- Shell 转义防护（Windows 路径含反斜杠，禁用 POSIX 转义） ----
        try:
            safeArgs = shlex.split(command, posix=False)
            if not safeArgs:
                return ToolResult.Fail("Empty command", toolName=self.name)
        except ValueError as exc:
            return ToolResult.Fail(
                f"Command parsing failed: {exc}", toolName=self.name
            )

        # ---- 工作目录限制 ----
        cwd = self.workingDir or None

        # ---- 不允许空命令 ----
        if not command.strip():
            return ToolResult.Fail("Empty command", toolName=self.name)

        try:
            proc = await asyncio.create_subprocess_shell(
                command,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd,
            )

            # ---- 后台模式：存储进程并立即返回 terminalId ----
            if is_background:
                terminalId = str(uuid.uuid4())[:8]
                self._backgroundProcesses[terminalId] = proc
                self._backgroundCommands[terminalId] = command[:200]
                return ToolResult.Ok(
                    f"Command started in background (terminalId: {terminalId})\n"
                    f"Command: {command[:200]}",
                    toolName=self.name,
                )

            try:
                stdout, stderr = await asyncio.wait_for(
                    proc.communicate(), timeout=timeout
                )
            except asyncio.TimeoutError:
                proc.kill()
                await proc.wait()
                return ToolResult.Fail(
                    f"Command timed out after {timeout}s: {command[:200]}",
                    toolName=self.name,
                )

            output = (stdout or b"").decode("utf-8", errors="replace")
            errorOutput = (stderr or b"").decode("utf-8", errors="replace")

            parts: list[str] = []
            if output:
                if len(output) > MAX_OUTPUT_LENGTH:
                    output = output[:MAX_OUTPUT_LENGTH] + "\n... (output truncated)"
                parts.append(output)
            if errorOutput:
                if len(errorOutput) > MAX_OUTPUT_LENGTH:
                    errorOutput = errorOutput[:MAX_OUTPUT_LENGTH] + "\n... (stderr truncated)"
                parts.append(f"[stderr]\n{errorOutput}")

            resultText = "\n".join(parts) if parts else "(no output)"
            resultText = f"[Exit code: {proc.returncode}]\n{resultText}"

            return ToolResult.Ok(resultText, toolName=self.name)

        except Exception as exc:
            return ToolResult.Fail(
                f"Command execution failed: {exc}\nCommand: {command[:200]}",
                toolName=self.name,
            )

    # ---- 安全校验 ----

    def _ValidateCommand(self, command: str, allowUnsafe: bool = False) -> str:
        """校验命令安全性，返回空字符串表示通过，否则返回拒绝原因。

        校验顺序：
        1. 危险模式正则匹配（含命令替换、进程替换等绕过手段）——始终启用
        2. 逐子命令段校验黑名单（按 &&、||、|、;、& 拆分）——始终启用
        3. 逐子命令段校验白名单（仅当白名单非空且 allowUnsafe=False 时）

        Args:
            command: 待校验的命令字符串。
            allowUnsafe: 为 True 时跳过白名单校验，仅依黑名单与危险模式。
        """
        if not command.strip():
            return "Empty command"

        # 1. 危险模式正则匹配（整条命令行）
        for pattern in self.dangerousPatterns:
            if pattern.search(command):
                return f"Command matches dangerous pattern: {pattern.pattern}"

        # 2 & 3. 逐子命令段校验黑/白名单
        segments = self._ExtractBaseCommands(command)
        if not segments:
            return "Empty command"

        for baseCommand in segments:
            if baseCommand in self.blockedCommands:
                return f"Command '{baseCommand}' is in the blocked list"
            if not allowUnsafe and self.allowedCommands and baseCommand not in self.allowedCommands:
                return (
                    f"Command '{baseCommand}' is not in the allowed list. "
                    f"Allowed: {', '.join(sorted(self.allowedCommands))}"
                )

        return ""

    @classmethod
    def _ExtractBaseCommands(cls, command: str) -> list[str]:
        """将复合命令拆分为各子命令段，提取每段的基命令名（小写、去路径）。

        按 Shell 控制操作符（&&、||、|、;、&、换行）拆分，对每段提取基名。

        例: 'echo ok && git status | findstr x'
            → ['echo', 'git', 'findstr']
        """
        bases: list[str] = []
        for segment in _SEGMENT_SPLIT_RE.split(command):
            base = cls._ExtractSegmentBase(segment)
            if base:
                bases.append(base)
        return bases

    @staticmethod
    def _ExtractSegmentBase(segment: str) -> str:
        """提取单个子命令段的基名称（去除路径与参数）。

        例: 'C:\\Program Files\\Git\\bin\\git.exe status' → 'git.exe' → 'git'
            'npm install' → 'npm'。
        """
        stripped = segment.strip()
        if not stripped:
            return ""

        try:
            parts = shlex.split(stripped)
            base = parts[0] if parts else ""
        except ValueError:
            tokens = stripped.split()
            base = tokens[0] if tokens else ""

        if not base:
            return ""
        # Windows 路径用反斜杠，os.path.basename 在 Windows 上可正确处理
        baseName = os.path.basename(base).lower()
        # 去掉 .exe / .cmd / .bat 等扩展名，保留纯命令名
        for ext in (".exe", ".cmd", ".bat", ".com", ".ps1"):
            if baseName.endswith(ext):
                baseName = baseName[:-len(ext)]
                break
        return baseName
