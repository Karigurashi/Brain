"""AgentSdk —— 外部 App 多群消息收发入口。

封装 AgentPool[T]，以泛型 T 为 Key 管理 Agent。
App 层唯一入口，所有 Agent 操作统一走 SDK。
"""

from __future__ import annotations

from typing import Generic, Optional, TypeVar

from agent.component.data import AgentConfig

from .agentPool import AgentEventListener, AgentPool

T = TypeVar("T")


class AgentSdk(Generic[T]):
    """Agent SDK，外部 App 多群消息收发入口。

    内部维护 AgentPool[T]，Key 自动创建 Agent。
    默认最大 20 并发消息。

    Usage::

        sdk = AgentSdk[str](modelName="deepseek-chat")
        sdk.AddListener("group-123", lambda e: print(e.content))
        sdk.SendMessage("group-123", "Hello")
        sdk.RemoveListener("group-123", callback)
        sdk.Destroy("group-123")
    """

    def __init__(
        self,
        modelName: Optional[str] = None,
        agentConfig: Optional[AgentConfig] = None,
        maxConcurrent: int = 20,
    ) -> None:
        self._pool: AgentPool[T] = AgentPool[T](
            modelName=modelName,
            agentConfig=agentConfig,
            maxConcurrent=maxConcurrent,
        )

    # ---- 消息发送 ----

    def SendMessage(
        self,
        key: T,
        message: str,
    ) -> None:
        self._pool.Send(key, message)

    async def SendMessageAsync(
        self,
        key: T,
        message: str,
    ) -> None:
        await self._pool.SendAsync(key, message)

    # ---- 事件监听 ----

    def AddListener(self, key: T, listener: AgentEventListener) -> None:
        self._pool.AddListener(key, listener)

    def RemoveListener(self, key: T, listener: AgentEventListener) -> None:
        self._pool.RemoveListener(key, listener)

    # ---- 会话持久化 ----

    def SaveSession(self, key: T, relativePath: str) -> None:
        self._pool.SaveSession(key, relativePath)

    def LoadSession(self, key: T, relativePath: str) -> bool:
        return self._pool.LoadSession(key, relativePath)

    # ---- 会话管理 ----

    def NewSession(self, key: T) -> int:
        return self._pool.NewSession(key)

    def ClearSession(self, key: T) -> int:
        return self._pool.ClearSession(key)

    def GetActiveSessionId(self, key: T) -> int:
        return self._pool.GetActiveSessionId(key)

    def GetSessionIds(self, key: T) -> list[int]:
        return self._pool.GetSessionIds(key)

    def GetSessionMessageCount(self, key: T, sessionId: int) -> int:
        return self._pool.GetSessionMessageCount(key, sessionId)

    def SaveSessionToMarkdown(self, key: T) -> int:
        return self._pool.SaveSessionToMarkdown(key)

    # ---- LLM 查询 ----

    def GetModelName(self, key: T) -> str:
        return self._pool.GetModelName(key)

    def GetProviderName(self, key: T) -> str:
        return self._pool.GetProviderName(key)

    def SwitchModel(self, key: T, modelName: str) -> bool:
        return self._pool.SwitchModel(key, modelName)

    def GetTotalPromptTokens(self, key: T) -> int:
        return self._pool.GetTotalPromptTokens(key)

    def GetTotalCompletionTokens(self, key: T) -> int:
        return self._pool.GetTotalCompletionTokens(key)

    def GetLastPromptTokens(self, key: T) -> int:
        return self._pool.GetLastPromptTokens(key)

    def GetLastCompletionTokens(self, key: T) -> int:
        return self._pool.GetLastCompletionTokens(key)

    def GetLastCacheHitRate(self, key: T) -> float:
        return self._pool.GetLastCacheHitRate(key)

    # ---- 上下文 ----

    async def CompactContextAsync(self, key: T, force: bool = False) -> int:
        return await self._pool.CompactContextAsync(key, force=force)

    # ---- 工具 ----

    def GetToolCount(self, key: T) -> int:
        return self._pool.GetToolCount(key)

    def GetAllTools(self, key: T) -> list[dict]:
        return self._pool.GetAllTools(key)

    # ---- 配置 ----

    def GetAgentConfig(self, key: T) -> AgentConfig:
        return self._pool.GetAgentConfig(key)

    # ---- Harness ----

    async def RebuildHarnessAsync(self, key: T) -> int:
        return await self._pool.RebuildHarnessAsync(key)

    # ---- 生命周期 ----

    def Cancel(self, key: T) -> None:
        self._pool.Cancel(key)

    def IsRunning(self, key: T) -> bool:
        return self._pool.IsRunning(key)

    def Destroy(self, key: T) -> None:
        self._pool.Destroy(key)