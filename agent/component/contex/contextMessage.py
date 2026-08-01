"""上下文消息 —— Session 中存储的标准消息类型，带唯一 ID 和 LOD 标记。"""

from __future__ import annotations

import copy
import time
import uuid
from dataclasses import dataclass, field
from typing import Optional

from common.const import ERole
from llm.provider.chatMessage import ChatMessage

from .eContextLodLevel import EContextLodLevel


@dataclass(slots=True)
class ContextMessage:
    """Session 中存储的单条消息。

    role/content 直接复用 ChatMessage，不再单独存储，避免 ToModelMessages 时重复创建对象。

    Attributes:
        messageId: 唯一标识（数值型 UUID）。
        chatMessage: 关联的 ChatMessage 实例（role/content 的来源）。
        lodLevel: LOD 等级。
        createdAt: 消息创建时间戳（自动生成）。
        isSummary: 是否为压缩摘要消息。
        skipPersist: 是否跳过 ContentStore 落盘（含冷卸载），源已在磁盘时为 True。
    """

    chatMessage: ChatMessage
    lodLevel: EContextLodLevel
    messageId: int = field(default_factory=lambda: uuid.uuid4().int)
    createdAt: int = field(default_factory=lambda: int(time.time()))
    isAgedOut: bool = False
    isSummary: bool = False
    skipPersist: bool = False

    def __init__(
        self,
        chatMessage: ChatMessage,
        lodLevel: EContextLodLevel,
        messageId: int | None = None,
        isAgedOut: bool = False,
        isSummary: bool = False,
        skipPersist: bool = False,
        createdAt: int | None = None,
    ) -> None:
        self.chatMessage = chatMessage
        self.messageId = messageId if messageId is not None else uuid.uuid4().int
        self.lodLevel = lodLevel
        self.createdAt = createdAt if createdAt is not None else int(time.time())
        self.isAgedOut = isAgedOut
        self.isSummary = isSummary
        self.skipPersist = skipPersist

    # ---- role / content 属性（代理到 ChatMessage）----

    @property
    def role(self) -> ERole:
        return self.chatMessage.role

    @property
    def content(self) -> str:
        return self.chatMessage.content

    @content.setter
    def content(self, value: str) -> None:
        self.chatMessage.content = value
        self.chatMessage.InvalidateCache()

    # ---- 静态工厂 ----

    @staticmethod
    def Create(
        chatMessage: ChatMessage,
        lodLevel: EContextLodLevel,
        messageId: int | None = None,
        skipPersist: bool = False,
    ) -> ContextMessage:
        """静态工厂：创建 ContextMessage，lodLevel 由调用方显式传入。

        LOD 分类职责在 ContextComponent，不在此工厂内自动判定。

        Returns:
            构造好的 ContextMessage。
        """
        return ContextMessage(
            chatMessage=chatMessage,
            lodLevel=lodLevel,
            messageId=messageId,
            skipPersist=skipPersist,
        )

    # ---- 复制 ----

    def Clone(self, *, newMessageId: bool = True) -> "ContextMessage":
        """深拷贝消息，供 Subagent fork / merge 使用。"""
        cm = self.chatMessage
        clonedChat = ChatMessage(
            role=cm.role,
            content=cm.content,
            thinkingContent=cm.thinkingContent,
            toolCalls=copy.deepcopy(cm.toolCalls) if cm.toolCalls else None,
            toolCallId=cm.toolCallId,
        )
        return ContextMessage(
            chatMessage=clonedChat,
            lodLevel=self.lodLevel,
            messageId=uuid.uuid4().int if newMessageId else self.messageId,
            isAgedOut=self.isAgedOut,
            isSummary=self.isSummary,
            skipPersist=self.skipPersist,
        )
