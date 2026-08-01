"""GroupComponent —— 群组管理组件，由 BaseChannel 装配挂载。

Agent 通讯完全委托给 AgentSdk（channel.Sdk）：
- 消息发送 → sdk.SendMessage（fire-and-forget）
- 事件监听 → sdk.AddListener / RemoveListener
- 会话持久化 → sdk.SaveSession / LoadSession
- 查询/管理 → sdk 全部 API
"""

from __future__ import annotations

from typing import Dict, List, Optional

from common.cancellationToken import CancellationToken
from common.logger import Logger

from ...channelComponent import BaseChannelComponent
from ...channelMessage import ChannelMessage
from .groupContext import GroupContext


class GroupComponent(BaseChannelComponent):
    """群组管理组件 —— 管理 GroupContext 集合，通讯委托 channel.Sdk。

    由 BaseChannel.__init__ 装配挂载，通过 channel.GetComponent(GroupComponent) 访问。

    Usage::

        channel = BaseChannel()
        group = channel.GetComponent(GroupComponent).EnsureGroup("group_123", "My Group")
    """

    def __init__(self) -> None:
        super().__init__()
        self._groups: Dict[str, GroupContext] = {}

    # ---- BaseComponent 生命周期 ----

    def OnDestroy(self) -> None:
        pass

    # ---- 群组管理 ----

    def EnsureGroup(
        self,
        groupId: str,
        groupName: str = "",
    ) -> GroupContext:
        existing = self._groups.get(groupId)
        if existing is not None:
            return existing

        self._RegisterListener(groupId)
        self._channel.Sdk.LoadSession(groupId, self._SessionPath(groupId))  # type: ignore[union-attr]

        group = GroupContext(groupId, groupName)
        self._groups[groupId] = group
        self._channel.Platform.OnGroupCreated(groupId)  # type: ignore[union-attr]
        Logger.Info(
            f"BaseChannel: group created: groupId={groupId}, groupName={groupName}"
        )
        return group

    async def RemoveGroupAsync(
        self,
        groupId: str,
        cancellationToken: Optional[CancellationToken] = None,
    ) -> bool:
        group = self._groups.pop(groupId, None)
        if group is None:
            return False

        self._SaveSessionInternal(groupId)
        self._channel.Sdk.Destroy(groupId)  # type: ignore[union-attr]
        self._channel.Platform.OnGroupRemoved(groupId)  # type: ignore[union-attr]
        Logger.Info(f"BaseChannel: group removed: groupId={groupId}")
        return True

    def GetGroup(self, groupId: str) -> Optional[GroupContext]:
        return self._groups.get(groupId)

    def GetGroupIds(self) -> List[str]:
        return list(self._groups.keys())

    @property
    def GroupCount(self) -> int:
        return len(self._groups)

    # ---- 消息发送（委托 channel.Sdk） ----

    def SendMessage(
        self,
        groupId: str,
        message: ChannelMessage,
    ) -> None:
        self._channel.Sdk.SendMessage(groupId, message.content)  # type: ignore[union-attr]

    async def SendMessageAsync(
        self,
        groupId: str,
        message: ChannelMessage,
    ) -> None:
        await self._channel.Sdk.SendMessageAsync(groupId, message.content)  # type: ignore[union-attr]

    # ---- 查询 API（委托 channel.Sdk） ----

    def GetModelName(self, groupId: str) -> Optional[str]:
        try:
            return self._channel.Sdk.GetModelName(groupId)  # type: ignore[union-attr]
        except KeyError:
            return None

    def GetActiveSessionId(self, groupId: str) -> int:
        try:
            return self._channel.Sdk.GetActiveSessionId(groupId)  # type: ignore[union-attr]
        except KeyError:
            return 0

    def GetLastTokenUsage(self, groupId: str) -> tuple[int, int, float]:
        try:
            sdk = self._channel.Sdk  # type: ignore[union-attr]
            return (
                sdk.GetLastPromptTokens(groupId),
                sdk.GetLastCompletionTokens(groupId),
                sdk.GetLastCacheHitRate(groupId),
            )
        except KeyError:
            return (0, 0, 0.0)

    # ---- 批量销毁 ----

    async def DestroyAllGroupsAsync(self) -> None:
        for groupId in list(self._groups.keys()):
            group = self._groups.pop(groupId, None)
            if group is not None:
                self._SaveSessionInternal(groupId)
                self._channel.Sdk.Destroy(groupId)  # type: ignore[union-attr]
                self._channel.Platform.OnGroupRemoved(groupId)  # type: ignore[union-attr]

    # ---- 内部 ----

    def _RegisterListener(self, groupId: str) -> None:
        def _OnEvent(event):
            self._channel.Platform.OnAgentEventSync(groupId, event)  # type: ignore[union-attr]

        self._channel.Sdk.AddListener(groupId, _OnEvent)  # type: ignore[union-attr]

    def _SaveSessionInternal(self, groupId: str) -> None:
        self._channel.Sdk.SaveSession(groupId, self._SessionPath(groupId))  # type: ignore[union-attr]

    def _SessionPath(self, groupId: str) -> str:
        namespace = self._channel.__class__.__name__  # type: ignore[union-attr]
        return f"app/{namespace.lower()}/{groupId}.json"