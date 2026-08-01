"""GroupContext —— 单群上下文，纯数据类。

每个群（如飞书群、Discord Channel）对应一个 GroupContext，
仅持有群标识信息，所有 Agent 操作全部委托 AgentSdk。
"""

from __future__ import annotations


class GroupContext:
    """单群上下文 —— 纯数据类，仅持有群标识。

    Agent 操作全部由 AgentSdk 统一管理，GroupContext 不持有任何 Agent 引用。

    Attributes:
        groupId: 群唯一标识。
        groupName: 群显示名称。
    """

    def __init__(self, groupId: str, groupName: str = "") -> None:
        self.groupId: str = groupId
        self.groupName: str = groupName