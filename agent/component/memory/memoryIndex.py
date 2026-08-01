"""INDEX.md 只读索引管理器 —— 记忆导航层。

INDEX.md 是 Memory 系统的 LOD0 注入入口，ContextAssembler 只加载
INDEX.md（< 500 tokens），然后按需读取具体的 memory/*.md 页面。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .memoryStore import MemoryStore


class MemoryIndex:
    """INDEX.md 只读管理器，加载并提供 INDEX.md 内容作为上下文块。

    使用方式::

        store = MemoryStore("/path/to/memory")
        index = MemoryIndex(store)
        blocks = index.ToContextBlocks()
    """

    def __init__(self, store: "MemoryStore") -> None:
        self._store = store
        self._rawContent = ""
        self._Load()

    def _Load(self) -> None:
        """从 INDEX.md 加载原始内容。"""
        raw = self._store.ReadFile(self._store.IndexPath)
        if raw:
            self._rawContent = raw.strip()

    def ToContextBlocks(self) -> list[str]:
        """生成供 ContextAssembler 注入 LOD0 的文本块列表。"""
        if not self._rawContent:
            return []
        return [self._rawContent]

    @property
    def EntryCount(self) -> int:
        """索引条目数（按 - [[ 行计数）。"""
        if not self._rawContent:
            return 0
        return sum(1 for line in self._rawContent.split("\n") if line.strip().startswith("- [["))
