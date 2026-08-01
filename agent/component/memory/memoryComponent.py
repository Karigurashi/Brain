"""MemoryComponent —— 跨会话持久化记忆组件。

作为 IComponent 可挂载到 BaseAgent，通过 OnInitialize/OnDestroy 感知生命周期。
提供会话摘要持久化（写 sessions/YYYY-MM-DD/{sessionId}.md）和 INDEX.md 上下文注入（LOD0）。

目录结构（位于 workspace/memory/）::

    {workspace/memory/}/
        sessions/               # 不可变会话摘要（按日期子目录）
            YYYY-MM-DD/
                {sessionId}.md
        memory/                 # 持久记忆
            INDEX.md            # 导航索引（LOD0 注入入口）
            LOG.md              # 追加式操作日志

使用方式::

    agent.AddComponent(MemoryComponent)
    memComp.SaveToMemory(123, "用户偏好 4 空格缩进")
    blocks = memComp.LoadContextBlocks()
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from agent.core.baseComponent import BaseComponent
from common.logger import Logger

if TYPE_CHECKING:
    from agent.core.baseAgent import BaseAgent


class MemoryComponent(BaseComponent):
    """跨会话持久化记忆组件。

    挂载到 BaseAgent 后自动可用，卸载时清理内部引用。
    """

    def __init__(self) -> None:
        self._store = None
        self._index = None

    # ---- IComponent 生命周期 ----

    def OnInitialize(self, agent: BaseAgent) -> None:
        """挂载后初始化，创建存储和索引。"""
        from agent.component.data.dataComponent import DataComponent
        from .memoryStore import MemoryStore
        from .memoryIndex import MemoryIndex

        dataComp = agent.GetComponent(DataComponent)
        memoryDir = dataComp.config.memoryDir

        self._store = MemoryStore(memoryDir)
        self._index = MemoryIndex(self._store)

    def OnDestroy(self) -> None:
        """从 BaseAgent 卸载时回调，清理引用。"""
        self._store = None
        self._index = None

    # ---- Context 注入 ----

    def LoadContextBlocks(self) -> list[str]:
        """从 INDEX.md 加载 LOD0 上下文块。

        只加载 INDEX.md（< 500 tokens），不含具体页面内容。
        """
        return self._index.ToContextBlocks()

    # ---- Session 持久化 ----

    def SaveToMemory(
        self,
        sessionId: int,
        body: str,
        messageCount: int,
        toolsUsed: list[str] | None = None,
        compactedCount: int = 0,
        compressedUpToTurnIndex: int = -1,
        created: str | None = None,
    ) -> bool:
        """保存会话内容到 sessions/YYYY-MM-DD/{sessionId}.md。

        通过 MemoryStore 走原子写入、会话裁剪、LOG.md 记录。

        Args:
            sessionId: 会话 ID。
            body: 已格式化的 Markdown 正文（含消息列表、工具清单或摘要等）。
            messageCount: 消息总数。
            toolsUsed: 使用过的工具名称列表。
            compactedCount: 被压缩的消息数。
            compressedUpToTurnIndex: 压缩覆盖到的 turn 索引。
            created: 创建时间字符串，默认使用当前时间。

        Returns:
            是否保存成功。
        """
        if not body.strip():
            return False

        now = created or time.strftime("%Y-%m-%dT%H:%M:%S")
        hasCompression = compressedUpToTurnIndex >= 0

        meta = {
            "session_id": sessionId,
            "created": now,
            "message_count": str(messageCount),
            "tools_used": ", ".join(toolsUsed) if toolsUsed else "none",
            "compacted_count": str(compactedCount),
            "has_compression": str(hasCompression).lower(),
            "compressed_up_to_turn": str(compressedUpToTurnIndex),
        }
        frontmatter = self._store.BuildFrontmatter(meta)
        content = frontmatter + body

        dateStr = now[:10]
        ok = self._store.SaveSession(sessionId, content, dateStr)
        if ok:
            toolStr = f"tools={len(toolsUsed)}" if toolsUsed else "tools=0"
            self._store.AppendLog(
                f"Saved session: {sessionId}... "
                f"(msgs={messageCount}, {toolStr})"
            )
            Logger.Info(f"MemoryComponent: saved session {sessionId}...")
        return ok

    def ReadSession(self, sessionId: int) -> str | None:
        """读取 sessions/*/{sessionId}.md 并剥离 frontmatter，返回正文。"""
        return self._store.ReadSession(sessionId)

    @property
    def SessionsDir(self) -> str:
        """sessions/ 目录路径，供外部写入快照等文件。"""
        return self._store.SessionsDir
