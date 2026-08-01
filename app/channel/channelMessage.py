"""Channel 标准化消息信封 —— 统一各平台入站消息格式。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class ChannelMessage:
    """入站消息信封。

    各平台适配器将平台原始事件转换为此统一格式后投递给 Channel。
    Channel 按 groupId 路由到对应 GroupContext，进而驱动 Agent 执行。

    Attributes:
        groupId: 群 / 会话唯一标识（飞书 chat_id、Discord channel_id 等）。
        userId: 发送者唯一标识。
        content: 消息文本内容。
        userName: 发送者显示名称。
        groupName: 群显示名称（仅在首次创建群组时使用）。
    """

    groupId: str
    userId: str
    content: str
    userName: str = ""
    groupName: str = ""
