"""AgentPool —— 泛型 Agent 池，以泛型 T 作为 Key 管理 Agent 实例。

SDK 层唯一 Agent 入口，App 层不持有任何 Agent 引用，
全部操作通过 AgentPool 完成。
"""

from __future__ import annotations

import asyncio
from typing import Callable, Generic, Optional, TypeVar

from common.cancellationToken import CancellationToken
from common.logger import Logger

from agent.component.data import AgentConfig
from agent.component.eventBus.agentStreamEvent import AgentStreamEvent
from agent.component.eventBus.eventBusComponent import EventBusComponent
from agent.core.baseAgent import BaseAgent

T = TypeVar("T")

AgentEventListener = Callable[[AgentStreamEvent], None]


class AgentPool(Generic[T]):
    """泛型 Agent 池，以泛型 T 作为 Key，内部自动创建 Agent。

    支持任意可哈希类型作为 Key（str、int、enum 等）。
    默认最大 20 并发消息。

    Usage::

        pool = AgentPool[str](modelName="deepseek-chat")
        pool.AddListener("chat-001", lambda e: print(e.content))
        await pool.SendAsync("chat-001", "Hello")
        pool.RemoveListener("chat-001", callback)
        pool.Destroy("chat-001")
    """

    def __init__(
        self,
        modelName: Optional[str] = None,
        agentConfig: Optional[AgentConfig] = None,
        maxConcurrent: int = 20,
    ) -> None:
        self._modelName: str = modelName or ""
        self._agentConfig: AgentConfig = agentConfig or AgentConfig()
        self._maxConcurrent: int = maxConcurrent
        self._agents: dict[T, BaseAgent] = {}
        self._activeTokens: dict[T, CancellationToken] = {}
        self._activeTasks: dict[T, asyncio.Task[None]] = {}
        self._sendLocks: dict[T, asyncio.Lock] = {}
        self._runIds: dict[T, int] = {}
        self._semaphore: asyncio.Semaphore | None = (
            asyncio.Semaphore(maxConcurrent) if maxConcurrent > 0 else None
        )

    # ---- 属性 ----

    @property
    def Count(self) -> int:
        return len(self._agents)

    @property
    def MaxConcurrent(self) -> int:
        return self._maxConcurrent

    @property
    def Keys(self) -> list[T]:
        return list(self._agents.keys())

    def Contains(self, key: T) -> bool:
        return key in self._agents

    def Clear(self) -> None:
        for key in list(self._agents.keys()):
            self._ClearEventListeners(key)
        count = len(self._agents)
        self._agents.clear()
        if self._semaphore is not None:
            for _ in range(count):
                self._semaphore.release()

    # ============================================================
    # 消息发送
    # ============================================================

    def _GetSendLock(self, key: T) -> asyncio.Lock:
        lock = self._sendLocks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            self._sendLocks[key] = lock
        return lock

    async def _AwaitPreviousRunAsync(self, key: T) -> None:
        """Cancel 并等待上一轮 Run 的 finally/EmitDone 结束，再允许 BeginRun。"""
        prevToken = self._activeTokens.get(key)
        if prevToken is not None and not prevToken.IsCancellationRequested:
            prevToken.Cancel()
        prevTask = self._activeTasks.get(key)
        if prevTask is not None and not prevTask.done():
            try:
                await prevTask
            except Exception:
                pass

    async def SendAsync(
        self,
        key: T,
        message: str,
    ) -> None:
        """同 key：Cancel 旧 run → 等其 EmitDone 落盘 → 再 BeginRun(新 id) → 开跑。

        禁止在旧 finally 前切换 runId，否则旧事件会被打上新 runId 污染新卡。
        """
        agent = self._GetOrCreate(key)
        task: asyncio.Task[None] | None = None

        # 锁外等待旧 run；持锁只做「确认空闲 + BeginRun + 挂 task」，避免死锁
        while True:
            await self._AwaitPreviousRunAsync(key)
            async with self._GetSendLock(key):
                prevTask = self._activeTasks.get(key)
                if prevTask is not None and not prevTask.done():
                    continue

                semaphoreAcquired = False
                try:
                    if self._semaphore is not None:
                        await self._semaphore.acquire()
                        semaphoreAcquired = True

                    runId = self._runIds.get(key, 0) + 1
                    self._runIds[key] = runId
                    agent.GetComponent(EventBusComponent).BeginRun(runId)
                    token = CancellationToken()
                    self._activeTokens[key] = token

                    async def _RunBodyAsync() -> None:
                        me = asyncio.current_task()
                        try:
                            await agent.RunAsync(message, token)
                        finally:
                            if self._activeTokens.get(key) is token:
                                self._activeTokens.pop(key, None)
                            if me is not None and self._activeTasks.get(key) is me:
                                self._activeTasks.pop(key, None)
                            if self._semaphore is not None:
                                self._semaphore.release()

                    task = asyncio.create_task(_RunBodyAsync())
                    self._activeTasks[key] = task
                    semaphoreAcquired = False  # 所有权交给 _RunBodyAsync.finally
                finally:
                    if semaphoreAcquired and self._semaphore is not None:
                        self._semaphore.release()
                break

        assert task is not None
        await task

    def Send(
        self,
        key: T,
        message: str,
    ) -> None:
        asyncio.create_task(self.SendAsync(key, message))

    # ============================================================
    # 事件监听
    # ============================================================

    def AddListener(self, key: T, listener: AgentEventListener) -> None:
        agent = self._GetOrCreate(key)
        eventBus = agent.GetComponent(EventBusComponent)
        eventBus.AddListener(listener)

    def RemoveListener(self, key: T, listener: AgentEventListener) -> None:
        agent = self._Get(key)
        eventBus = agent.GetComponent(EventBusComponent)
        eventBus.RemoveListener(listener)

    # ============================================================
    # 会话持久化
    # ============================================================

    def SaveSession(self, key: T, relativePath: str) -> None:
        agent = self._agents.get(key)
        if agent is None:
            return
        self._SaveSessionForAgent(agent, relativePath)

    def LoadSession(self, key: T, relativePath: str) -> bool:
        agent = self._agents.get(key)
        if agent is None:
            return False
        return self._LoadSessionForAgent(agent, relativePath)

    # ============================================================
    # 会话管理
    # ============================================================

    def NewSession(self, key: T) -> int:
        from agent.component.session.sessionComponent import SessionComponent
        return self._Get(key).GetComponent(SessionComponent).NewSession()

    def ClearSession(self, key: T) -> int:
        from agent.component.session.sessionComponent import SessionComponent
        return self._Get(key).GetComponent(SessionComponent).ClearSession()

    def GetActiveSessionId(self, key: T) -> int:
        from agent.component.session.sessionComponent import SessionComponent
        return self._Get(key).GetComponent(SessionComponent).ActiveSessionId

    def GetSessionIds(self, key: T) -> list[int]:
        from agent.component.session.sessionComponent import SessionComponent
        return self._Get(key).GetComponent(SessionComponent).GetSessionIds()

    def GetSessionMessageCount(self, key: T, sessionId: int) -> int:
        from agent.component.session.sessionComponent import SessionComponent
        session = self._Get(key).GetComponent(SessionComponent).GetSession(sessionId)
        return session.GetMessageCount() if session else 0

    def SaveSessionToMarkdown(self, key: T) -> int:
        from agent.component.session.sessionComponent import SessionComponent
        return self._Get(key).GetComponent(SessionComponent).SaveToMarkdown()

    # ============================================================
    # LLM 查询
    # ============================================================

    def GetModelName(self, key: T) -> str:
        from agent.component.llm.llmComponent import LLMComponent
        return self._Get(key).GetComponent(LLMComponent).modelName

    def GetProviderName(self, key: T) -> str:
        from agent.component.llm.llmComponent import LLMComponent
        return self._Get(key).GetComponent(LLMComponent).providerName

    def SwitchModel(self, key: T, modelName: str) -> bool:
        from llm import LLMManager
        from agent.component.data.dataComponent import DataComponent
        from agent.component.llm.llmComponent import LLMComponent

        try:
            newLlm = LLMManager.GetProvider(modelName)
        except KeyError:
            return False

        agent = self._Get(key)
        agent.GetComponent(DataComponent).llm = newLlm
        agent.GetComponent(LLMComponent).llm = newLlm
        return True

    def GetTotalPromptTokens(self, key: T) -> int:
        from agent.component.llm.llmComponent import LLMComponent
        return self._Get(key).GetComponent(LLMComponent).TotalPromptTokens

    def GetTotalCompletionTokens(self, key: T) -> int:
        from agent.component.llm.llmComponent import LLMComponent
        return self._Get(key).GetComponent(LLMComponent).TotalCompletionTokens

    def GetLastPromptTokens(self, key: T) -> int:
        from agent.component.llm.llmComponent import LLMComponent
        return self._Get(key).GetComponent(LLMComponent).LastPromptTokens

    def GetLastCompletionTokens(self, key: T) -> int:
        from agent.component.llm.llmComponent import LLMComponent
        return self._Get(key).GetComponent(LLMComponent).LastCompletionTokens

    def GetLastCacheHitRate(self, key: T) -> float:
        from agent.component.llm.llmComponent import LLMComponent
        return self._Get(key).GetComponent(LLMComponent).LastCacheHitRate

    # ============================================================
    # 上下文
    # ============================================================

    async def CompactContextAsync(self, key: T, force: bool = False) -> int:
        from agent.component.contex.contextComponent import ContextComponent
        return await self._Get(key).GetComponent(ContextComponent).CompactAsync(force=force)

    # ============================================================
    # 工具
    # ============================================================

    def GetToolCount(self, key: T) -> int:
        from agent.component.tool.toolComponent import ToolComponent
        return self._Get(key).GetComponent(ToolComponent).Count()

    def GetAllTools(self, key: T) -> list[dict]:
        from agent.component.tool.toolComponent import ToolComponent
        tools = self._Get(key).GetComponent(ToolComponent).GetAll()
        return [
            {"name": name, "category": tool.category.name, "description": tool.description}
            for name, tool in tools.items()
        ]

    # ============================================================
    # 配置
    # ============================================================

    def GetAgentConfig(self, key: T) -> AgentConfig:
        from agent.component.data.dataComponent import DataComponent
        return self._Get(key).GetComponent(DataComponent).config

    # ============================================================
    # Harness
    # ============================================================

    async def RebuildHarnessAsync(self, key: T) -> int:
        from agent.component.harness.harnessComponent import HarnessComponent
        from agent.component.tool.toolComponent import ToolComponent
        agent = self._Get(key)
        await agent.GetComponent(HarnessComponent).BuildAsync(force=True)
        return agent.GetComponent(ToolComponent).Count()

    # ============================================================
    # 生命周期
    # ============================================================

    def Cancel(self, key: T) -> None:
        token = self._activeTokens.get(key)
        if token is not None:
            token.Cancel()

    def IsRunning(self, key: T) -> bool:
        return key in self._activeTokens

    def Destroy(self, key: T) -> None:
        self.Cancel(key)
        self._activeTokens.pop(key, None)
        self._activeTasks.pop(key, None)
        agent = self._agents.pop(key, None)
        if agent is None:
            return
        agent.Destroy()

    # ============================================================
    # 内部
    # ============================================================

    def _GetOrCreate(self, key: T) -> BaseAgent:
        if key not in self._agents:
            from agent import AgentManager
            self._agents[key] = AgentManager.CreateAgent(self._modelName, self._agentConfig)
            Logger.Info(f"AgentPool: agent auto-created for key '{key}'")
        return self._agents[key]

    def _Get(self, key: T) -> BaseAgent:
        agent = self._agents.get(key)
        if agent is None:
            raise KeyError(f"AgentPool: key '{key}' not found")
        return agent

    def _ClearEventListeners(self, key: T) -> None:
        agent = self._agents.get(key)
        if agent is not None:
            self._ClearEventListenersForAgent(agent)

    def _ClearEventListenersForAgent(self, agent: BaseAgent) -> None:
        eventBus = agent.GetComponent(EventBusComponent)
        eventBus.RemoveAllListeners()

    def _SaveSessionForAgent(self, agent: BaseAgent, relativePath: str) -> None:
        import os
        from agent.component.session.sessionComponent import SessionComponent
        from agent.component.memory.memoryComponent import MemoryComponent

        sessionComp = agent.GetComponent(SessionComponent)
        memComp = agent.GetComponent(MemoryComponent)
        session = sessionComp.ActiveSession
        if session is None:
            return

        path = os.path.join(memComp.SessionsDir, relativePath)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(session.ToJson())
        except OSError:
            pass

    def _LoadSessionForAgent(self, agent: BaseAgent, relativePath: str) -> bool:
        import os
        from agent.component.session.sessionComponent import SessionComponent
        from agent.component.memory.memoryComponent import MemoryComponent
        from agent.component.session.session import Session

        memComp = agent.GetComponent(MemoryComponent)
        path = os.path.join(memComp.SessionsDir, relativePath)
        if not os.path.isfile(path):
            return False

        try:
            with open(path, "r", encoding="utf-8") as f:
                session = Session.FromJson(f.read())
        except Exception as exc:
            Logger.Error(f"AgentPool load session snapshot failed: {exc}")
            return False

        sessionComp = agent.GetComponent(SessionComponent)
        sessionComp.RestoreSession(session)
        return True