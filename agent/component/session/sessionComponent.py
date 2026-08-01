"""SessionComponent —— Session 管理器，可挂载到 BaseAgent。

SessionComponent 管理多个 Session 实例，维护一个活跃 Session 引用。
对外暴露与旧版兼容的消息管理接口，全部代理到活跃 Session。

作为 BaseComponent 可挂载到 BaseAgent，通过 OnInitialize/OnDestroy 感知生命周期。
其他 Component（如 ContextComponent）通过依赖注入持有 SessionComponent 引用。
"""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from agent.component.contex.contextMessage import ContextMessage
from agent.component.contex.eContextLodLevel import EContextLodLevel
from agent.core.baseComponent import BaseComponent
from agent.component.session.session import Session
from common.const import ERole
from common.logger import Logger
from common.serializeUtil import SerializeUtil

if TYPE_CHECKING:
    from agent.core.baseAgent import BaseAgent
    from agent.component.memory import MemoryComponent


class SessionComponent(BaseComponent):
    """Agent 运行时的 Session 管理器，可挂载为 Component。

    SessionComponent 是"账本管理员"——持有多个 Session，每个 Session
    完整记录所有消息（含压缩摘要）。ContextComponent 是"调度器"——
    从活跃 Session 读取，决定发给 LLM 什么，压缩后回写。

    Attributes:
        memory: 关联的持久化 Memory 实例（可选）。
        ActiveSessionId: 当前活跃会话的 ID。
        SessionCount: 已创建的会话总数。
    """

    def __init__(self) -> None:
        self.memory: MemoryComponent | None = None
        self._sessions: dict[str, Session] = {}
        self._activeSession: Session | None = None

    # ---- BaseComponent 生命周期 ----

    def OnInitialize(self, agent: BaseAgent) -> None:
        """挂载后初始化，自动注入 MemoryComponent 和 LLMComponent 并创建默认 Session。"""
        from agent.component.memory import MemoryComponent

        self.memory = agent.GetComponent(MemoryComponent)
        self._activeSession = Session()
        self._sessions[self._activeSession.sessionId] = self._activeSession

    def OnDestroy(self) -> None:
        """从 BaseAgent 卸载时回调，清空所有 Session。"""
        self.ClearAllSessions()

    # ---- Session 管理（新增） ----

    @property
    def ActiveSession(self) -> Session | None:
        """当前活跃的 Session 实例。"""
        return self._activeSession

    @property
    def ActiveSessionId(self) -> int:
        """当前活跃 Session 的 ID。"""
        return self._activeSession.sessionId if self._activeSession else 0

    @property
    def SessionCount(self) -> int:
        """已创建的会话总数。"""
        return len(self._sessions)

    def NewSession(self) -> int:
        """创建新会话并设为活跃。

        当前活跃会话（如有）会被归档（持久化摘要到 Memory），
        然后创建全新 Session 实例。旧 Session 中的 RESIDENT
        内容会拷贝到新 Session，保证 harness 初始填充的规则、
        技能前缀等常驻内容跨会话复用，无需反复重建。

        Returns:
            新创建的 sessionId。
        """
        if self._activeSession is not None:
            self.SaveToMemory()

        session = Session()
        # 从旧 Session 拷贝 RESIDENT 内容到新 Session
        if self._activeSession is not None:
            session.ReplaceResidents(list(self._activeSession.residentMessages))

        self._sessions[session.sessionId] = session
        self._activeSession = session
        return session.sessionId

    def ClearSession(self) -> int:
        """清空当前活跃会话的对话消息，不触发归档保存。

        RESIDENT 常驻内容保留，sessionId 不变。

        Returns:
            当前活跃会话的 sessionId，无活跃会话时返回 0。
        """
        if self._activeSession is None:
            return 0
        self._activeSession.Clear()
        return self._activeSession.sessionId

    def RestoreSession(self, session: Session) -> None:
        """将反序列化好的 Session 直接设为当前活跃会话。

        原有活跃会话会被替换（不触发归档）。用于离线接力恢复。
        """
        self._sessions[session.sessionId] = session
        self._activeSession = session

    def SwitchSession(self, sessionId: int) -> bool:
        """切换到指定会话。

        切换前自动归档当前活跃会话。若目标 sessionId 不存在则返回 False。

        Args:
            sessionId: 目标会话 ID。

        Returns:
            是否切换成功。
        """
        target = self._sessions.get(sessionId)
        if target is None:
            return False

        if self._activeSession is not None and self._activeSession is not target:
            self.SaveToMemory()

        self._activeSession = target
        return True

    def GetSession(self, sessionId: int) -> Session | None:
        """按 ID 获取 Session 实例。

        Args:
            sessionId: 会话唯一标识。

        Returns:
            找到的 Session，不存在时返回 None。
        """
        return self._sessions.get(sessionId)

    def GetSessionIds(self) -> list[int]:
        """返回所有已创建会话的 ID 列表。"""
        return list(self._sessions.keys())

    def RemoveSession(self, sessionId: int) -> bool:
        """移除指定会话。

        若移除的是活跃会话，则自动将活跃会话置为 None，
        调用方应在移除后通过 NewSession 或 SwitchSession 设置新活跃会话。

        Args:
            sessionId: 待移除的会话 ID。

        Returns:
            是否成功移除。
        """
        session = self._sessions.pop(sessionId, None)
        if session is None:
            return False
        if session is self._activeSession:
            self._activeSession = None
        return True

    def ClearAllSessions(self) -> None:
        """清空所有 Session。"""
        self._sessions.clear()
        self._activeSession = None

    # ---- 会话持久化 ----

    def SaveToMemory(self) -> int:
        """将活跃会话全量序列化为 JSON 持久化到 memory/sessions/YYYY-MM-DD/{sessionId}.md。

        核心保证：Session 全量可存储、可从文件加载组装回来。

        Returns:
            实际写入的消息数量，失败时返回 0。
        """
        session = self._activeSession
        if session is None:
            return 0

        messages = session.residentMessages + session.conversationMessages
        if not messages:
            return 0

        if self.memory is None:
            return 0

        body = session.ToJson()
        now = time.strftime("%Y-%m-%dT%H:%M:%S")

        toolNames: set[str] = set()
        for msg in messages:
            tcs = msg.chatMessage.toolCalls
            if tcs:
                for tc in tcs:
                    toolNames.add(tc.name)

        ok = self.memory.SaveToMemory(
            sessionId=session.sessionId,
            body=body,
            messageCount=len(messages),
            toolsUsed=sorted(toolNames) if toolNames else None,
            created=now,
        )
        return len(messages) if ok else 0

    def SaveToMarkdown(self) -> int:
        """将活跃会话全量序列化为人类可读的 Markdown 格式，持久化到 memory/sessions/YYYY-MM-DD/{sessionId}.md。

        与 SaveToMemory（纯 JSON 序列化）不同，本方法生成结构化 Markdown 正文：
          - 每条消息按 role 分区，标注 LOD 等级与是否为摘要
          - 工具调用以 ```json 代码块展示参数
          - TOOL 消息关联回其工具名

        Returns:
            实际写入的消息数量，失败时返回 0。
        """
        session = self._activeSession
        if session is None:
            return 0

        if self.memory is None:
            return 0

        allMsgs = session.residentMessages + session.conversationMessages
        if not allMsgs:
            return 0

        now = time.strftime("%Y-%m-%dT%H:%M:%S")
        rCount = len(session.residentMessages)
        cCount = len(session.conversationMessages)

        # 预计算 tool_call_id → tool_name 映射，供 TOOL 消息回链
        toolNameMap: dict[str, str] = {}
        for msg in allMsgs:
            tcs = msg.chatMessage.toolCalls
            if tcs:
                for tc in tcs:
                    toolNameMap[tc.id] = tc.name

        lines: list[str] = []

        # ---- Header ----
        lines.append(f"# Session {session.sessionId}")
        lines.append("")
        lines.append(f"- **Created:** {now}")
        lines.append(f"- **Messages:** {len(allMsgs)} total ({rCount} RESIDENT, {cCount} conversation)")
        lines.append("")
        lines.append("---")
        lines.append("")

        # ---- Messages ----
        for msg in allMsgs:
            role = msg.role.value.capitalize()
            headerParts = [f"## [{role.upper()}]"]

            # LOD 标记
            lodTag = msg.lodLevel.name
            if msg.lodLevel == EContextLodLevel.RESIDENT:
                headerParts.append(f"`{lodTag}`")

            # 摘要标记
            if msg.isSummary:
                headerParts.append("*(summary)*")

            tcs = msg.chatMessage.toolCalls

            # ASSISTANT 带 tool_calls
            if tcs:
                headerParts.append("→ tool_calls")

            # TOOL 消息回链工具名
            if msg.role == ERole.TOOL and msg.chatMessage.toolCallId:
                toolName = toolNameMap.get(msg.chatMessage.toolCallId, "?")
                headerParts.append(f"← `{toolName}`")

            lines.append(" ".join(headerParts))
            lines.append("")

            thinking = (msg.chatMessage.thinkingContent or "").strip()
            if thinking:
                lines.append("### Thinking")
                lines.append("")
                lines.append(thinking)
                lines.append("")

            # 工具调用详情
            if tcs:
                for tc in tcs:
                    argsStr = SerializeUtil.ToJson(tc.arguments)
                    lines.append(f"- `{tc.name}` (id: `{tc.id}`)")
                    lines.append("  ```json")
                    lines.append(f"  {argsStr}")
                    lines.append("  ```")
                if msg.content.strip():
                    lines.append("")
                    lines.append(msg.content.strip())

            # 普通文本内容
            elif msg.content.strip():
                lines.append(msg.content.strip())

            lines.append("")
            lines.append("---")
            lines.append("")

        # ---- 工具统计 ----
        toolNames: set[str] = set()
        for msg in allMsgs:
            tcs = msg.chatMessage.toolCalls
            if tcs:
                for tc in tcs:
                    toolNames.add(tc.name)

        ok = self.memory.SaveToMemory(
            sessionId=session.sessionId,
            body="\n".join(lines),
            messageCount=len(allMsgs),
            toolsUsed=sorted(toolNames) if toolNames else None,
            created=now,
        )
        return len(allMsgs) if ok else 0

    def ReadFromMemory(self, sessionId: int) -> Session | None:
        """从 memory/sessions/*/{sessionId}.md 读取并还原完整 Session。

        从 JSON 反序列化，重建消息列表、residentMessages 及 lod4Count。

        Args:
            sessionId: 目标会话 ID。

        Returns:
            还原的 Session 实例，不存在或解析失败时返回 None。
        """
        if self.memory is None:
            return None

        body = self.memory.ReadSession(sessionId)
        if body is None:
            return None

        try:
            return Session.FromJson(body)
        except (json.JSONDecodeError, KeyError, TypeError) as e:
            Logger.Error(f"SessionComponent.ReadFromMemory failed: sessionId={sessionId}, {e}")
            return None

    # ---- 属性代理（向后兼容） ----

    @property
    def sessionId(self) -> str:
        """活跃会话的 ID（向后兼容）。"""
        return self._activeSession.sessionId

    @property
    def residentMessages(self) -> list[ContextMessage]:
        """活跃会话的 RESIDENT 常驻消息列表（只读）。"""
        return self._activeSession.residentMessages

    @property
    def conversationMessages(self) -> list[ContextMessage]:
        """活跃会话的非 RESIDENT 对话消息列表（只读）。"""
        return self._activeSession.conversationMessages

    # ---- 消息管理（代理到活跃 Session，向后兼容） ----

    def Append(self, msg: ContextMessage) -> None:
        """追加一条 ContextMessage 到活跃会话。"""
        self._activeSession.Append(msg)

    def AppendBatch(self, msgs: list[ContextMessage]) -> None:
        """批量追加消息到活跃会话。"""
        self._activeSession.AppendBatch(msgs)

    def GetMessageCount(self) -> int:
        """返回活跃会话消息总数。"""
        return self._activeSession.GetMessageCount()

    def ClearLod4(self) -> int:
        """清除活跃会话中所有 LOD4 消息。"""
        return self._activeSession.ClearLod4()

    def ApplyCompactionResult(self, compactedMessages: list[ContextMessage]) -> None:
        """使用压缩产物替换活跃会话的消息列表，保留 RESIDENT。"""
        self._activeSession.ApplyCompactionResult(compactedMessages)

    def FixOrphanedToolCalls(self) -> int:
        """修复活跃 Session 中孤立的 tool_call 链。

        Returns:
            被移除的消息数量。
        """
        return self._activeSession.FixOrphanedToolCalls()

    def GetStats(self) -> dict:
        """返回活跃会话的统计信息。"""
        return self._activeSession.GetStats()
