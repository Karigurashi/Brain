"""StoreComponent —— 文件缓存落盘组件。

挂载到 BaseAgent 后自动可用，通过 GetComponent(StoreComponent) 获取。
负责大内容的外部文件存储、加载、LRU 淘汰管理。

用法::

    agent.AddComponent(StoreComponent)
    storeComp = agent.GetComponent(StoreComponent)
    path = storeComp.Store("large content")
    content = storeComp.Load(path)
"""

from __future__ import annotations

import hashlib
import os
import tempfile
import time
from typing import TYPE_CHECKING

from agent.core.baseComponent import BaseComponent

if TYPE_CHECKING:
    from agent.core.baseAgent import BaseAgent


class StoreComponent(BaseComponent):
    """文件缓存落盘组件。

    当工具返回大结果时（行数/字节数超过阈值），原始内容写入外部文件，
    上下文中仅保留路径引用 + 摘要，AI 需要时可调用 read 工具按路径重新加载。

    容量管理双层约束：
    - maxTotalSize：外存目录总容量上限（字节）。
    - maxFileCount：外存目录最大文件数。
    - LRU 淘汰：超出任一约束时按最近访问时间排序，删除最久未访问的文件。

    通过 DataComponent.config 读取 storeDir / storeMaxTotalSize / storeMaxFileCount。
    enablePersist 为 False 时 storeDir 为 None，所有操作退化为空或原样返回。
    """

    def __init__(self) -> None:
        self._storeDir: str | None = None
        self._maxTotalSize: int = 0
        self._maxFileCount: int = 0

    # ---- BaseComponent 生命周期 ----

    def OnInitialize(self, agent: BaseAgent) -> None:
        """挂载后初始化，从 DataComponent.config 读取存储配置。"""
        from agent.component.data.dataComponent import DataComponent

        config = agent.GetComponent(DataComponent).config
        if config.enablePersist:
            self._storeDir = os.path.abspath(config.storeDir)
            self._maxTotalSize = config.storeMaxTotalSize
            self._maxFileCount = config.storeMaxFileCount

    def OnDestroy(self) -> None:
        """从 BaseAgent 卸载时回调，释放资源。"""
        self._storeDir = None

    # ---- 公开接口 ----

    def Store(self, content: str, skipEviction: bool = False) -> str | None:
        """将大内容原子写入外存，返回文件路径。

        采用 tmpfile + os.replace 保证并发安全。
        写入前检查总容量，超限时按 LRU 淘汰腾出空间。
        skipEviction 为 True 时跳过淘汰检查，适用于批量写入场景，
        调用方应在批量写入结束后手动调用 Evict()。
        storeDir 为 None 时返回 None。
        """
        if self._storeDir is None:
            return None

        os.makedirs(self._storeDir, exist_ok=True)
        if not skipEviction:
            self._EvictIfNeeded(len(content.encode("utf-8")))

        contentHash = hashlib.md5(content.encode("utf-8")).hexdigest()[:12]
        timestamp = int(time.time() * 1000)
        filename = f"{timestamp}_{contentHash}.txt"
        filepath = os.path.join(self._storeDir, filename)

        fd, tmpPath = tempfile.mkstemp(dir=self._storeDir, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(content)
            os.replace(tmpPath, filepath)
        except Exception:
            if os.path.exists(tmpPath):
                os.unlink(tmpPath)
            raise

        return os.path.abspath(filepath)

    def Load(self, path: str, refreshAccess: bool = True) -> str | None:
        """按路径加载外存内容。

        Args:
            path: 相对于 storeDir 的文件路径。
            refreshAccess: 是否刷新文件 mtime 用于 LRU 淘汰排序。
        """
        if self._storeDir is None:
            return None
        fullPath = os.path.join(self._storeDir, os.path.basename(path)) if not os.path.isabs(path) else path
        try:
            with open(fullPath, "r", encoding="utf-8") as f:
                content = f.read()
        except (FileNotFoundError, OSError):
            return None

        if refreshAccess:
            try:
                now = time.time()
                os.utime(fullPath, (now, now))
            except OSError:
                pass

        return content

    def GetSummary(self, path: str, maxChars: int = 200) -> str:
        """获取外存内容的前 N 个字符作为摘要。"""
        content = self.Load(path, refreshAccess=False)
        if content is None:
            return f"[内容不可用: {path}]"
        if len(content) <= maxChars:
            return content
        return content[:maxChars] + "..."

    def GetTotalSize(self) -> int:
        """计算外存目录中所有文件的总字节数。"""
        if self._storeDir is None or not os.path.isdir(self._storeDir):
            return 0
        totalSize = 0
        with os.scandir(self._storeDir) as entries:
            for entry in entries:
                if entry.is_file():
                    try:
                        totalSize += entry.stat().st_size
                    except OSError:
                        pass
        return totalSize

    def Evict(self) -> int:
        """执行一次 LRU 淘汰，将目录恢复到容量/文件数限制内。

        适用于批量 Store(skipEviction=True) 后的集中清理。
        """
        return self._EvictIfNeeded(0, incomingCount=0)

    def BuildPersistedPreview(
        self, path: str, content: str, previewChars: int = 500
    ) -> str:
        """生成大结果落盘后的预览文本，参照 Claude Code <persisted-output> 标签。
        storeDir 为 None 时原样返回 content。
        """
        if self._storeDir is None:
            return content

        charCount = len(content)
        preview = content[:previewChars]
        truncated = charCount > previewChars

        lines = [
            f"<persisted-output file=\"{path}\">",
            f"Size: {charCount} chars | Stored: {path}",
        ]
        if truncated:
            lines.append("--- preview (first chars) ---")
            lines.append(preview)
            lines.append(f"... ({charCount - previewChars} more chars)")
        else:
            lines.append(content)
        lines.append(
            "Use read_file with start_line/end_line to read specific sections "
            "of this file. Avoid reading the entire file at once."
        )
        lines.append("</persisted-output>")

        return "\n".join(lines)

    # ---- 内部 LRU 淘汰 ----

    _HIGH_WATER_RATIO: float = 1.5

    def _EvictIfNeeded(self, incomingSize: int, incomingCount: int = 1) -> int:
        """容量或文件数超限时按 LRU 淘汰文件，为新写入腾出空间。

        采用高水位/低水位策略：达到阈值 1.5 倍时触发淘汰，清理至 1.0 倍。
        incomingCount 默认为 1（单次 Store 调用）；批量写入后统一清理时应传 0。
        """
        if self._maxTotalSize <= 0 and self._maxFileCount <= 0:
            return 0

        if self._storeDir is None or not os.path.isdir(self._storeDir):
            return 0

        fileEntries = []
        with os.scandir(self._storeDir) as entries:
            for entry in entries:
                if not entry.is_file():
                    continue
                try:
                    stat = entry.stat()
                    fileEntries.append((stat.st_mtime, entry.path, stat.st_size))
                except OSError:
                    continue

        currentSize = sum(e[2] for e in fileEntries)
        currentCount = len(fileEntries)

        highWaterSize = int(self._maxTotalSize * self._HIGH_WATER_RATIO)
        highWaterCount = int(self._maxFileCount * self._HIGH_WATER_RATIO)
        sizeExceeded = self._maxTotalSize > 0 and (currentSize + incomingSize > highWaterSize)
        countExceeded = self._maxFileCount > 0 and (currentCount + incomingCount > highWaterCount)
        if not sizeExceeded and not countExceeded:
            return 0

        fileEntries.sort(key=lambda e: e[0])

        evicted = 0
        freedSize = 0
        # 目标：清理至 1.0 倍阈值
        sizeTarget = (currentSize + incomingSize) - self._maxTotalSize if sizeExceeded else 0
        countTarget = (currentCount + incomingCount) - self._maxFileCount if countExceeded else 0

        for _, filepath, size in fileEntries:
            satisfiedSize = not sizeExceeded or freedSize >= sizeTarget
            satisfiedCount = not countExceeded or (currentCount - evicted) <= self._maxFileCount
            if satisfiedSize and satisfiedCount:
                break
            try:
                os.remove(filepath)
                freedSize += size
                evicted += 1
            except OSError:
                pass

        return evicted
