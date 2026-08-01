"""CommandContext —— 指令处理上下文，提供服务化 API 与响应输出。

Agent 全部经 AgentSdk 访问，CommandContext 不持有 Agent 引用。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, List

from agent.sdk import AgentSdk

if TYPE_CHECKING:
    from ...baseChannel import BaseChannel
    from ...channelMessage import ChannelMessage
    from .commandRegistry import CommandRegistry


class CommandContext:
    """指令处理上下文 —— 服务化 API + 响应输出。

    由 Platform.CreateCommandContext 创建，传入 AgentSdk、群组 ID 和原始消息。
    命令 handler 通过此上下文调用服务方法、输出响应、请求退出等。

    Attributes:
        GroupId: 群组唯一标识。
        UserId: 发送者唯一标识。
        UserName: 发送者显示名称。
    """

    def __init__(
        self,
        channel: BaseChannel,
        groupId: str,
        message: ChannelMessage,
        registry: CommandRegistry,
    ) -> None:
        self._channel: BaseChannel = channel
        self._sdk: AgentSdk[str] = channel.Sdk
        self._groupId: str = groupId
        self._message: ChannelMessage = message
        self._registry: CommandRegistry = registry
        self._responseBuffer: List[str] = []

    # ---- 群组 / 消息信息 ----

    @property
    def GroupId(self) -> str:
        return self._groupId

    @property
    def UserId(self) -> str:
        return self._message.userId

    @property
    def UserName(self) -> str:
        return self._message.userName

    @property
    def Channel(self) -> BaseChannel:
        return self._channel

    @property
    def Registry(self) -> CommandRegistry:
        return self._registry

    # ---- Session 服务 ----

    def NewSession(self) -> int:
        return self._sdk.NewSession(self._groupId)

    def ClearSession(self) -> int:
        return self._sdk.ClearSession(self._groupId)

    def GetActiveSessionId(self) -> int:
        return self._sdk.GetActiveSessionId(self._groupId)

    def GetSessionIds(self) -> list[int]:
        return self._sdk.GetSessionIds(self._groupId)

    def GetSessionMessageCount(self, sessionId: int) -> int:
        return self._sdk.GetSessionMessageCount(self._groupId, sessionId)

    def SaveSessionToMarkdown(self) -> int:
        return self._sdk.SaveSessionToMarkdown(self._groupId)

    # ---- LLM 服务 ----

    def GetModelName(self) -> str:
        return self._sdk.GetModelName(self._groupId)

    def GetProviderName(self) -> str:
        return self._sdk.GetProviderName(self._groupId)

    def SwitchModel(self, modelName: str) -> bool:
        return self._sdk.SwitchModel(self._groupId, modelName)

    def GetTotalPromptTokens(self) -> int:
        return self._sdk.GetTotalPromptTokens(self._groupId)

    def GetTotalCompletionTokens(self) -> int:
        return self._sdk.GetTotalCompletionTokens(self._groupId)

    def GetLastPromptTokens(self) -> int:
        return self._sdk.GetLastPromptTokens(self._groupId)

    def GetLastCompletionTokens(self) -> int:
        return self._sdk.GetLastCompletionTokens(self._groupId)

    def GetLastCacheHitRate(self) -> float:
        return self._sdk.GetLastCacheHitRate(self._groupId)

    # ---- Context 服务 ----

    async def CompactContextAsync(self, force: bool = False) -> int:
        return await self._sdk.CompactContextAsync(self._groupId, force=force)

    # ---- Tool 服务 ----

    def GetToolCount(self) -> int:
        return self._sdk.GetToolCount(self._groupId)

    def GetAllTools(self) -> list[dict]:
        return self._sdk.GetAllTools(self._groupId)

    # ---- Data 服务 ----

    def GetAgentConfig(self) -> object:
        return self._sdk.GetAgentConfig(self._groupId)

    # ---- Harness 服务 ----

    async def RebuildHarnessAsync(self) -> int:
        return await self._sdk.RebuildHarnessAsync(self._groupId)

    # ---- 输出 ----

    def Print(self, text: str) -> None:
        self._responseBuffer.append(text)

    def PrintDim(self, text: str) -> None:
        self._responseBuffer.append(text)

    def PrintWarning(self, text: str) -> None:
        self._responseBuffer.append(text)

    def PrintError(self, text: str) -> None:
        self._responseBuffer.append(text)

    def GetResponseText(self) -> str:
        return "\n".join(self._responseBuffer)

    @property
    def HasResponse(self) -> bool:
        return len(self._responseBuffer) > 0

    # ---- 格式化工具 ----

    @staticmethod
    def FormatK(value: int) -> str:
        return f"{value / 1000.0:.1f}k"