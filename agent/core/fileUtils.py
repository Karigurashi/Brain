"""Agent Core 层文件工具共享模块 —— rg 检测、执行、.mangoIgnore 参数注入、Markdown 链接解析。

供 agent 内 grep / glob / skill / rule 等组件引用，全部为类级静态方法。
.mangoIgnore 路径从 Settings 懒加载。
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path


class FileUtils:
    """Agent 层文件静态工具 —— rg、.mangoIgnore、Markdown 相对链接解析。

    .mangoIgnore 路径从 Settings.AgentConfig().mangoIgnorePath 懒加载。
    """

    RG_NOT_FOUND_MSG = (
        "ripgrep (rg) not found in PATH. "
        "Install: winget install BurntSushi.ripgrep.MSVC"
    )

    # ---- 类级状态 ----

    _rgPath: str | None = None
    _rgChecked: bool = False
    _mangoIgnorePath: str | None = None

    # ==================== Settings ====================

    @classmethod
    def _EnsureSettings(cls) -> None:
        """从 Settings 懒加载 mangoIgnorePath（仅首次）。"""
        if cls._mangoIgnorePath is not None:
            return
        from setting import Settings
        cls._mangoIgnorePath = Settings.AgentConfig().mangoIgnorePath

    # ==================== ripgrep ====================

    @classmethod
    def DetectRg(cls) -> str | None:
        """检测 ripgrep 可用性，进程级缓存，避免重复扫描 PATH。"""
        if not cls._rgChecked:
            cls._rgPath = shutil.which("rg")
            cls._rgChecked = True
        return cls._rgPath

    @staticmethod
    def RunRg(cmd: list[str], timeout: float) -> tuple[str | None, str]:
        """执行 rg 子进程，返回 (stdout, 错误信息)。

        退出码 2 或子进程异常时 stdout 为 None。
        超时由调用方按工具 timeout 传入，保证子进程与工具超时对齐。
        """
        try:
            proc = subprocess.run(
                cmd, capture_output=True, text=True, timeout=timeout,
                encoding="utf-8", errors="replace",
            )
        except (subprocess.TimeoutExpired, FileNotFoundError, OSError) as exc:
            return None, str(exc)
        if proc.returncode == 2:
            return None, proc.stderr.strip() or "rg exited with code 2"
        return proc.stdout, ""

    # ==================== .mangoIgnore ====================

    @classmethod
    def AppendIgnoreFileArg(cls, cmd: list[str]) -> None:
        """若 .mangoIgnore 文件存在，向 rg 命令追加 --ignore-file 参数。"""
        cls._EnsureSettings()
        if cls._mangoIgnorePath and os.path.isfile(cls._mangoIgnorePath):
            cmd.extend(["--ignore-file", cls._mangoIgnorePath])

    # ==================== Markdown 链接解析 ====================

    @staticmethod
    def ResolveRelativeLinks(body: str, sourcePath: str) -> str:
        """将 Markdown 正文中的相对链接解析为绝对路径。

        基于 sourcePath 的父目录，将所有相对路径的 Markdown 链接
        ``[text](path)`` 和图片 ``![alt](path)`` 转换为绝对路径，
        使得 LLM 调用 Read 工具时能正确定位引用文件。

        绝对路径（以 ``/`` 或盘符开头）和外部 URL（``http://`` / ``https://``）
        以及锚点链接不做转换。
        """
        if not sourcePath:
            return body

        baseDir = Path(sourcePath).parent

        def _ResolveMatch(match: re.Match) -> str:
            prefix = match.group(1)  # '[' 或 '!['
            text = match.group(2)
            url = match.group(3)

            if url.startswith(("http://", "https://", "/", "#")):
                return match.group(0)
            if len(url) >= 2 and url[1] == ":":
                return match.group(0)

            resolved = str((baseDir / url).resolve())
            return f"{prefix}{text}]({resolved})"

        pattern = re.compile(r'(\!?\[)([^\]]*)\]\(([^)]+)\)')
        return pattern.sub(_ResolveMatch, body)
