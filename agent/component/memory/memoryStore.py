"""记忆文件存储层 —— 纯文件 I/O，管理 workspace/memory/ 目录下的 Markdown 文件。

职责：
- 目录结构初始化（sessions/YYYY-MM-DD/, memory/）
- Markdown 文件读写（含原子写入）
- 会话摘要持久化与自动裁剪
- 操作日志追加

不依赖 LLM，不依赖 Memory 抽象。
"""

from __future__ import annotations

import os
import tempfile
import time
from typing import Optional

from common.logger import Logger


class MemoryStore:
    """Markdown 文件 I/O 核心，封装目录结构和文件操作。

    目录结构::

        {workspace/memory/}/
            sessions/               # 不可变会话摘要（按日期子目录）
                YYYY-MM-DD/
                    {sessionId}.md
            memory/                 # 持久记忆
                INDEX.md            # 导航索引
                LOG.md              # 追加式操作日志
    """

    MAX_SESSIONS = 15
    PRUNE_COUNT = 5

    def __init__(self, baseDir: str) -> None:
        self._baseDir = baseDir
        self._InitDirs()

    # ---- 属性 ----

    @property
    def BaseDir(self) -> str:
        """记忆根目录。"""
        return self._baseDir

    @property
    def SessionsDir(self) -> str:
        return os.path.join(self._baseDir, "sessions")

    @property
    def MemoryDir(self) -> str:
        return os.path.join(self._baseDir, "memory")

    # ---- 目录初始化 ----

    def _InitDirs(self) -> None:
        """确保所有子目录存在。"""
        for d in (self.SessionsDir, self.MemoryDir):
            os.makedirs(d, exist_ok=True)

    # ---- 通用 Markdown 读写 ----

    @staticmethod
    def BuildFrontmatter(meta: dict[str, str]) -> str:
        """根据元数据字典生成 YAML frontmatter 字符串。"""
        if not meta:
            return ""
        lines = ["---"]
        for key, value in meta.items():
            lines.append(f'{key}: "{value}"')
        lines.append("---")
        return "\n".join(lines) + "\n"

    def ReadFile(self, filePath: str) -> str | None:
        """读取文件全部内容，不存在时返回 None。"""
        if not os.path.isfile(filePath):
            return None
        try:
            with open(filePath, "r", encoding="utf-8") as f:
                return f.read()
        except OSError as e:
            Logger.Error(f"MemoryStore.ReadFile failed: {filePath} | {e}")
            return None

    def WriteFile(self, filePath: str, content: str) -> bool:
        """原子写入文件，自动创建父目录。返回是否成功。

        实现路径：先写入同目录临时文件，再通过 os.replace 原子覆盖目标路径，
        避免写入中途进程崩溃导致文件被截断为不一致状态。
        """
        tmpPath: Optional[str] = None
        try:
            dirName = os.path.dirname(filePath) or "."
            os.makedirs(dirName, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", dir=dirName,
                delete=False, suffix=".tmp",
            ) as tmp:
                tmp.write(content)
                tmpPath = tmp.name
            os.replace(tmpPath, filePath)
            return True
        except OSError as e:
            if tmpPath and os.path.exists(tmpPath):
                try:
                    os.unlink(tmpPath)
                except OSError:
                    pass
            Logger.Error(f"MemoryStore.WriteFile failed: {filePath} | {e}")
            return False

    def AppendFile(self, filePath: str, content: str) -> bool:
        """追加写入文件，返回是否成功。"""
        try:
            os.makedirs(os.path.dirname(filePath), exist_ok=True)
            with open(filePath, "a", encoding="utf-8") as f:
                f.write(content)
            return True
        except OSError as e:
            Logger.Error(f"MemoryStore.AppendFile failed: {filePath} | {e}")
            return False

    def ListFiles(self, directory: str, extension: str = ".md") -> list[str]:
        """列出目录下所有指定扩展名的文件（仅文件名，不含路径）。"""
        if not os.path.isdir(directory):
            return []
        try:
            return sorted(
                f for f in os.listdir(directory)
                if f.endswith(extension) and os.path.isfile(os.path.join(directory, f))
            )
        except OSError:
            return []

    # ---- Session 读写 ----

    def SaveSession(self, sessionId: int, content: str, dateStr: str | None = None) -> bool:
        """保存会话摘要到 sessions/YYYY-MM-DD/{sessionId}.md，写入后自动裁剪超出上限的旧会话。"""
        dateFolder = dateStr or time.strftime("%Y-%m-%d")
        path = os.path.join(self.SessionsDir, dateFolder, f"{sessionId}.md")
        ok = self.WriteFile(path, content)
        if ok:
            self._PruneSessions(self.MAX_SESSIONS, self.PRUNE_COUNT)
        return ok

    def ReadSession(self, sessionId: int) -> str | None:
        """读取 sessions/*/{sessionId}.md 并剥离 YAML frontmatter，返回正文。

        优先搜索日期子目录，未找到则回退到扁平路径（向后兼容）。
        文件不存在或读取失败时返回 None。
        """
        path = self._FindSessionPath(sessionId)
        if path is None:
            return None
        raw = self.ReadFile(path)
        if raw is None:
            return None
        return self._StripFrontmatter(raw)

    @staticmethod
    def _StripFrontmatter(content: str) -> str:
        """剥离 YAML frontmatter（--- ... ---），返回正文部分。"""
        if content.startswith("---"):
            idx = content.find("---", 3)
            if idx != -1:
                return content[idx + 3:].lstrip("\n")
        return content

    def _FindSessionPath(self, sessionId: int) -> str | None:
        """在 sessions/ 下递归查找 {sessionId}.md，优先日期子目录，兜底扁平路径。"""
        targetName = f"{sessionId}.md"
        try:
            for entry in os.scandir(self.SessionsDir):
                if entry.is_dir():
                    candidate = os.path.join(entry.path, targetName)
                    if os.path.isfile(candidate):
                        return candidate
        except OSError:
            pass
        flatPath = os.path.join(self.SessionsDir, targetName)
        if os.path.isfile(flatPath):
            return flatPath
        return None

    def _CollectSessionFiles(self) -> list[tuple[str, float]]:
        """递归收集 sessions/ 下所有 .md 文件，返回 (完整路径, mtime) 列表。"""
        result: list[tuple[str, float]] = []
        try:
            for entry in os.scandir(self.SessionsDir):
                if entry.is_file() and entry.name.endswith(".md"):
                    try:
                        result.append((entry.path, entry.stat().st_mtime))
                    except OSError:
                        result.append((entry.path, 0.0))
                elif entry.is_dir():
                    try:
                        for sub in os.scandir(entry.path):
                            if sub.is_file() and sub.name.endswith(".md"):
                                try:
                                    result.append((sub.path, sub.stat().st_mtime))
                                except OSError:
                                    result.append((sub.path, 0.0))
                    except OSError:
                        pass
        except OSError:
            pass
        return result

    # ---- 会话裁剪 ----

    def _PruneSessions(self, maxCount: int, pruneCount: int) -> int:
        """会话数量超出 maxCount 时，按文件修改时间删除最旧的 pruneCount 条。

        遍历所有日期子目录收集 .md 文件，删除后自动清理空日期文件夹。

        Args:
            maxCount: 允许的最大会话文件数。
            pruneCount: 超出后删除的条数。

        Returns:
            实际删除的文件数。
        """
        filesWithMtime = self._CollectSessionFiles()
        if len(filesWithMtime) <= maxCount:
            return 0

        # 按文件修改时间升序（最旧在前）
        filesWithMtime.sort(key=lambda x: x[1])

        # 删除最旧的 pruneCount 条
        removed = 0
        for fpath, _ in filesWithMtime[:pruneCount]:
            try:
                os.remove(fpath)
                removed += 1
                fname = os.path.basename(fpath)
                Logger.Info(f"MemoryStore: pruned old session {fname[:-3][:8]}...")
                # 清理空日期文件夹
                parentDir = os.path.dirname(fpath)
                if parentDir != self.SessionsDir:
                    try:
                        if not os.listdir(parentDir):
                            os.rmdir(parentDir)
                    except OSError:
                        pass
            except OSError as e:
                Logger.Warning(f"MemoryStore: failed to prune {fpath}: {e}")

        if removed > 0:
            self.AppendLog(f"Pruned {removed} old session(s), remaining {len(filesWithMtime) - removed}")

        return removed

    # ---- LOG.md ----

    @property
    def LogPath(self) -> str:
        return os.path.join(self.MemoryDir, "LOG.md")

    def AppendLog(self, entry: str) -> bool:
        """追加一行操作日志。"""
        timestamp = time.strftime("%Y-%m-%dT%H:%M:%S")
        line = f"- [{timestamp}] {entry}\n"
        return self.AppendFile(self.LogPath, line)

    # ---- INDEX.md ----

    @property
    def IndexPath(self) -> str:
        return os.path.join(self.MemoryDir, "INDEX.md")
