"""SimpleAgent 对话节点 —— 通过 SimpleAgent 调用大模型并返回回复。"""

from agent import (
    AgentManager,
    AgentStreamEvent,
    EAgentStreamEventType,
    EventBusComponent,
    LLMComponent,
    SimpleAgent,
)

from ...core.baseNode import BaseNode, ENodeCategory, handler
from ...core.workflowMessage import WorkflowMessage
from ...core.nodeRegistry import NodeRegistry


@NodeRegistry.Register
class SimpleAgentNode(BaseNode):
    """SimpleAgent 对话节点 —— 使用 SystemPrompt + UserMessage 构建消息，调用指定模型。

    Config:
        ModelName: 模型名称（如 "deepseek-high"），为空则用默认模型。
        SystemPrompt: 系统提示词。
        UserMessage: 首轮用户消息（仅无上游时生效）。
        Temperature: 采样温度，默认 0.7。
        EnableThinking: 是否开启思考链（Anthropic Extended Thinking），默认关闭。

    节点间消息格式::

        {"role": "user", "content": "..."}

    下游 SimpleAgent 会将 role + content 原样写入对话历史，不做合并。
    """

    nodeType = "Action/SimpleAgent"
    category = ENodeCategory.ACTION
    displayName = "SimpleAgent"
    description = "调用大模型对话，返回生成文本"

    def __init__(self, **config) -> None:
        super().__init__(**config)
        self._agent: SimpleAgent | None = None
        self._agentModelName: str | None = None

    @classmethod
    def GetConfigSchema(cls) -> list[dict]:
        return [
            {"name": "ModelName", "type": "string", "default": "", "description": "模型名称（空=默认）"},
            {"name": "SystemPrompt", "type": "string", "default": "", "description": "系统提示词"},
            {"name": "UserMessage", "type": "string", "default": "", "description": "首轮用户消息（无上游时）"},
            {"name": "Temperature", "type": "number", "default": 0.7, "description": "采样温度（0-2），越高越随机"},
            {"name": "EnableThinking", "type": "boolean", "default": False, "description": "是否开启思考链（Anthropic Extended Thinking）"},
        ]

    @handler
    async def Handle(self, message: WorkflowMessage) -> None:
        """默认入口：接收 WorkflowMessage，提取 content 作为用户消息。"""
        userMessage = message.message or getattr(self, "UserMessage", "") or "hello"
        systemPrompt = getattr(self, "SystemPrompt", "") or ""
        await self._CallLLMAsync(systemPrompt, userMessage)

    @handler(inputType=dict)
    async def HandleDict(self, message: dict) -> None:
        content = message.get("content") or message.get("userMessage") or "hello"
        systemPrompt = message.get("systemPrompt") or getattr(self, "SystemPrompt", "") or ""
        await self._CallLLMAsync(systemPrompt, content)

    @handler(inputType=str)
    async def HandleStr(self, message: str) -> None:
        systemPrompt = getattr(self, "SystemPrompt", "") or ""
        await self._CallLLMAsync(systemPrompt, message)

    async def _CallLLMAsync(self, systemPrompt: str, userMessage: str) -> None:
        """核心逻辑：通过 SimpleAgent 流式调用 LLM、写回上下文。"""
        ctx = self.context
        if ctx is None:
            return

        modelName = getattr(self, "ModelName", "") or None
        temperature = float(getattr(self, "Temperature", 0.5) or 0.5)
        enableThinking = bool(getattr(self, "EnableThinking", False))

        # 按需创建 / 复用 SimpleAgent（modelName 变更时重建）
        if self._agent is None or self._agentModelName != modelName:
            self._agent = AgentManager.CreateSimpleAgent(modelName)
            self._agentModelName = modelName

        agent = self._agent
        llmComp = agent.GetComponent(LLMComponent)
        llmComp.RequestParams.temperature = temperature
        llmComp.RequestParams.enableThinking = enableThinking

        self._streamNodeId = ctx.CurrentNodeId
        self._streamExecutionRound = ctx.ExecutionRound
        self._streamEnableThinking = enableThinking
        self._streamFullContent = ""

        eventBusComp = agent.GetComponent(EventBusComponent)
        eventBusComp.AddListener(self._OnAgentStreamEvent)

        try:
            if systemPrompt:
                agent.SetSystemPrompt(systemPrompt)
            await agent.RunAsync(
                userMessage,
                ctx.CancellationToken,
                stream=True,
            )
        finally:
            eventBusComp.RemoveListener(self._OnAgentStreamEvent)

        if llmComp.TotalPromptTokens > 0:
            self._streamFullContent += f"\ntokens: in{llmComp.TotalPromptTokens} out{llmComp.TotalCompletionTokens}"

        ctx.Set(f"{self._streamNodeId}.Response", self._streamFullContent)

        await ctx.SendMessageAsync(WorkflowMessage(
            nodeId=self._streamNodeId,
            message=self._streamFullContent,
        ))

    def _OnAgentStreamEvent(self, event: AgentStreamEvent) -> None:
        """Agent 流式事件回调：累积文本并推送前端。"""
        from task.workflow.core.workflowEventData import EWorkflowEventType, WorkFlowEventData
        from task.workflow.core.baseNode import ENodeStatus

        ctx = self.context
        if ctx is None:
            return
        if event.eventType == EAgentStreamEventType.TEXT_COMPLETE:
            self._streamFullContent += event.content
            ctx.PushProgress(WorkFlowEventData(
                type=EWorkflowEventType.AI_CONTENT,
                nodeId=self._streamNodeId,
                message=event.content,
            ))
        elif event.eventType == EAgentStreamEventType.ERROR:
            ctx.PushProgress(WorkFlowEventData(
                type=EWorkflowEventType.NODE_STATUS,
                nodeId=self._streamNodeId,
                message=event.content,
                status=ENodeStatus.FAILED,
            ))
