"""LLMComponent —— 将 BaseLLM 封装为可挂载的 BaseComponent。

挂载到 BaseAgent 后，通过 BaseAgent.GetComponent(LLMComponent) 获取 LLM 实例、
工具绑定、用量追踪和四维调用能力。

重试机制已下沉至 llm/provider/BaseProvider 层，
LLMComponent 仅做透明代理，不再包含任何重试逻辑。

流式调用时，LLMComponent 内部持有 StringIO 缓冲区复用并自动推送
TextDelta / ThinkingDelta / TextComplete / ThinkingComplete 事件，
上层 Agent 无需自行管理缓冲区与事件推送。
"""

from __future__ import annotations

from io import StringIO
from typing import Iterator, Optional, TYPE_CHECKING

from agent.component.data import DataComponent
from agent.core.baseComponent import BaseComponent
from common.cancellationToken import CancellationToken
from llm.baseLLM import BaseLLM
from llm.llmRequestParams import LLMRequestParams
from llm.provider.chatMessage import ChatChunk, ChatMessage, ChatResponse, TokenUsage, ToolCall, ToolSpec
from llm.tokenEstimator import TokenEstimator

if TYPE_CHECKING:
    from agent.core.baseAgent import BaseAgent
    from agent.component.eventBus.eventBusComponent import EventBusComponent
    from agent.component.contex.contextMessage import ContextMessage


class LLMComponent(BaseComponent):
    """LLM 组件 —— 持有 BaseLLM、工具绑定、用量追踪和四维调用。

    挂载到 BaseAgent 后自动可用，卸载时清理状态。

    用法::

        agent = BaseAgent()
        llmComp = agent.AddComponent(LLMComponent)
        llmComp.llm = someBaseLLM
        response = llmComp.Invoke("Hello")
    """

    def __init__(self) -> None:
        self._llm: BaseLLM | None = None
        self._requestParams = LLMRequestParams()
        self._contentBuf = StringIO()             # 每轮复用，累积文本回复
        self._thinkingBuf = StringIO()            # 每轮复用，累积思考链
        self._lastThinkingContent = ""            # 最近一次调用的完整思考链
        self._lastPromptTokens = 0                # 最近一次调用的 promptTokens
        self._lastCompletionTokens = 0            # 最近一次调用的 completionTokens
        self._lastCacheHitRate = 0.0              # 最近一次调用的缓存命中率 (0-100)
        self._totalPromptTokens = 0               # 累计输入 token
        self._totalCompletionTokens = 0           # 累计输出 token
        self._eventBusComp: EventBusComponent | None = None
        self._tokenEstimator = TokenEstimator()   # 内嵌估算器，OnInitialize 时按模型名配置

    # ---- 生命周期 ----

    def OnInitialize(self, agent: BaseAgent) -> None:
        """挂载后注入 EventBusComponent，配置 TokenEstimator。"""
        dataComp = agent.GetComponent(DataComponent)
        self._llm = dataComp.llm
        # 运行时导入避免循环依赖
        from agent.component.eventBus.eventBusComponent import EventBusComponent
        self._eventBusComp = agent.GetComponent(EventBusComponent)
        self._tokenEstimator.Configure(modelName=self._llm.modelName)

    def OnDestroy(self) -> None:
        """从 BaseAgent 卸载时回调。"""
        pass

    # ---- 属性 ----

    @property
    def llm(self) -> BaseLLM:
        """获取底层 BaseLLM 实例，未初始化时抛出 RuntimeError。"""
        if self._llm is None:
            raise RuntimeError("LLMComponent.llm has not been initialized. Ensure Agent is constructed with a valid BaseLLM.")
        return self._llm

    @llm.setter
    def llm(self, value: BaseLLM) -> None:
        self._llm = value

    # ---- 元信息 ----

    @property
    def modelName(self) -> str:
        return self._llm.modelName

    @property
    def providerName(self) -> str:
        return self._llm.providerName

    @property
    def LastThinkingContent(self) -> str:
        """最近一次 LLM 调用的完整思考链，供上下文注入回传。"""
        return self._lastThinkingContent

    @property
    def LastPromptTokens(self) -> int:
        """最近一次 LLM 调用实际返回的 promptTokens，供 ContextComponent 增量估算。"""
        return self._lastPromptTokens

    @property
    def LastCompletionTokens(self) -> int:
        """最近一次 LLM 调用实际返回的 completionTokens。"""
        return self._lastCompletionTokens

    @property
    def LastCacheHitRate(self) -> float:
        """最近一次 LLM 调用的缓存命中率 (0-100)。"""
        return self._lastCacheHitRate

    @property
    def TotalPromptTokens(self) -> int:
        """累计输入 token 数。"""
        return self._totalPromptTokens

    @property
    def TotalCompletionTokens(self) -> int:
        """累计输出 token 数。"""
        return self._totalCompletionTokens

    # ---- 工具绑定 ----

    @property
    def RequestParams(self) -> LLMRequestParams:
        """当前请求参数（含工具列表）。"""
        return self._requestParams

    def BindTools(self, tools: list[ToolSpec]) -> None:
        """绑定工具列表，直接修改原始对象。"""
        self._requestParams.tools = tools if tools else None

    # ---- 用量追踪 ----

    def GetUsage(self) -> TokenUsage:
        """查询累计 Token 用量。"""
        return self._llm.totalUsage

    def ResetUsage(self) -> None:
        """重置累计用量。"""
        self._llm.ResetUsage()

    # ---- Token 估算 ----

    def EstimateTokens(self, messages: list[ContextMessage]) -> int:
        """估算 ContextMessage 列表的总 token 数。

        内部访问 cm.chatMessage 获取完整 ChatMessage，
        确保 content + toolCalls + toolCallId 全部计入估算，
        消除 ContextMessage 代理层遗漏 toolCalls/toolCallId 的偏差。
        """
        return sum(self._tokenEstimator.EstimateMessage(cm.chatMessage) for cm in messages)

    def EstimateText(self, text: str) -> int:
        """估算单段文本的 token 数。"""
        return self._tokenEstimator.Estimate(text)

    # ---- 消息归一化（三个明确签名，禁止 isinstance 分支） ----

    @staticmethod
    def FromStr(text: str) -> list[ChatMessage]:
        """从裸字符串构造单条 User 消息。"""
        return [ChatMessage.User(text)]

    @staticmethod
    def FromDicts(dicts: list[dict[str, str]]) -> list[ChatMessage]:
        """从 dict 列表构造 ChatMessage 列表。"""
        return [ChatMessage(role=d["role"], content=d["content"]) for d in dicts]

    @staticmethod
    def FromChatMessages(messages: list[ChatMessage]) -> list[ChatMessage]:
        """原样返回 ChatMessage 列表（浅拷贝）。"""
        return list(messages)

    async def InvokeAsync(
        self,
        messages: list[ChatMessage],
        turnIndex: int = 0,
        cancellationToken: Optional[CancellationToken] = None,
    ) -> ChatResponse:
        """非流式调用 LLM，内置事件推送。

        自动推送 TextComplete / ThinkingComplete 事件。
        异常会向上传播，由调用方决定错误处理策略。

        Args:
            messages: 对话消息列表。
            turnIndex: 当前推理轮次序号，透传至事件。
            cancellationToken: 取消令牌。

        Returns:
            ChatResponse 包含完整内容、思考链与工具调用列表。
        """
        response = await self._llm.InvokeAsync(
            messages,
            cancellationToken=cancellationToken,
            requestParams=self._requestParams,
        )

        content = response.content or ""
        thinking = response.reasoningContent or ""
        self._lastThinkingContent = thinking

        self._EmitTextEvent(content, turnIndex, isComplete=True)
        if thinking:
            self._EmitThinkingEvent(thinking, turnIndex, isComplete=True)

        if response.usage is not None:
            self._lastPromptTokens = response.usage.promptTokens
            self._lastCompletionTokens = response.usage.completionTokens
            self._lastCacheHitRate = self._CalcCacheHitRate(response.usage)
            self._totalPromptTokens += response.usage.promptTokens
            self._totalCompletionTokens += response.usage.completionTokens

        return response

    async def StreamAsync(
        self,
        messages: list[ChatMessage],
        turnIndex: int = 0,
        cancellationToken: Optional[CancellationToken] = None,
    ) -> ChatResponse:
        """流式调用 LLM，内置缓冲区管理与事件推送。

        自动推送 ThinkingDelta / TextDelta / ThinkingComplete / TextComplete 事件。
        异常会向上传播，由调用方决定错误处理策略。

        Args:
            messages: 对话消息列表。
            turnIndex: 当前推理轮次序号，透传至事件。
            cancellationToken: 取消令牌。

        Returns:
            ChatResponse 包含完整内容、思考链与工具调用列表。
        """
        self._ResetContentBuffer()
        self._ResetThinkingBuffer()
        toolCalls: list[ToolCall] | None = None
        lastUsage: TokenUsage | None = None

        async for chunk in self._llm.StreamAsync(
            messages,
            cancellationToken=cancellationToken,
            requestParams=self._requestParams,
        ):
            if chunk.reasoningContent:
                self._thinkingBuf.write(chunk.reasoningContent)
                self._EmitThinkingEvent(chunk.reasoningContent, turnIndex, isComplete=False)

            if chunk.content:
                self._contentBuf.write(chunk.content)
                self._EmitTextEvent(chunk.content, turnIndex, isComplete=False)

            if chunk.toolCalls:
                if toolCalls is None:
                    toolCalls = []
                toolCalls.extend(chunk.toolCalls)

            if chunk.usage is not None:
                lastUsage = chunk.usage

        content = self._contentBuf.getvalue()
        thinking = self._thinkingBuf.getvalue()
        self._lastThinkingContent = thinking

        self._EmitTextEvent(content, turnIndex, isComplete=True)
        if thinking:
            self._EmitThinkingEvent(thinking, turnIndex, isComplete=True)

        if lastUsage is not None:
            self._lastPromptTokens = lastUsage.promptTokens
            self._lastCompletionTokens = lastUsage.completionTokens
            self._lastCacheHitRate = self._CalcCacheHitRate(lastUsage)
            self._totalPromptTokens += lastUsage.promptTokens
            self._totalCompletionTokens += lastUsage.completionTokens

        return ChatResponse(
            content=content,
            reasoningContent=thinking,
            toolCalls=toolCalls,
            usage=lastUsage,
        )

    def _ResetContentBuffer(self) -> None:
        """重置内容缓冲区，复用 StringIO 实例避免内存分配。"""
        self._contentBuf.seek(0)
        self._contentBuf.truncate(0)

    def _ResetThinkingBuffer(self) -> None:
        """重置思考链缓冲区，复用 StringIO 实例避免内存分配。"""
        self._thinkingBuf.seek(0)
        self._thinkingBuf.truncate(0)

    @staticmethod
    def _CalcCacheHitRate(usage: TokenUsage) -> float:
        """根据 TokenUsage 计算缓存命中率 (0-100)。"""
        if usage.promptTokens <= 0:
            return 0.0
        return usage.cacheReadInputTokens / usage.promptTokens * 100.0

    def _EmitTextEvent(self, content: str, turnIndex: int, *, isComplete: bool) -> None:
        """推送文本事件。"""
        if isComplete:
            self._eventBusComp.EmitTextComplete(content, turnIndex)
        else:
            self._eventBusComp.EmitTextDelta(content, turnIndex)

    def _EmitThinkingEvent(self, content: str, turnIndex: int, *, isComplete: bool) -> None:
        """推送思考事件。"""
        if isComplete:
            self._eventBusComp.EmitThinkingComplete(content, turnIndex)
        else:
            self._eventBusComp.EmitThinkingDelta(content, turnIndex)
