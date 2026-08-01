"""Agent 对话节点 —— 通过完整 Agent（ReAct + 工具）调用大模型并返回回复。"""

from agent import (
    Agent,
    AgentStreamEvent,
    EAgentStreamEventType,
    EventBusComponent,
    LLMComponent,
)
from agent.agentManager import AgentManager
from agent.component.contex.contextComponent import ContextComponent
from agent.component.contex.eContextLodLevel import EContextLodLevel
from common.const import ERole

from ...core.baseNode import BaseNode, ENodeCategory, ENodeStatus, handler
from ...core.workflowMessage import WorkflowMessage
from ...core.nodeRegistry import NodeRegistry


@NodeRegistry.Register
class AgentNode(BaseNode):
    """Agent 对话节点 —— 使用完整 ReAct Agent（支持工具/技能/规则/MCP）。

    Config:
        ModelName: 模型名称（如 "deepseek-high"），为空则用默认模型。
        SystemPrompt: 系统提示词。
        UserMessage: 首轮用户消息（仅无上游时生效）。
        Temperature: 采样温度，默认 0.7。
        EnableThinking: 是否开启思考链，默认关闭。
        MaxTurns: 最大 ReAct 推理轮次，默认 25。
        AutoCompact: 回合后是否自动上下文压缩，默认开启。
        WorkspaceRoot: 工作区根目录，默认项目目录。

    节点间消息格式::

        {"role": "user", "content": "..."}

    下游 Agent 会将 role + content 原样写入对话历史，不做合并。
    """

    nodeType = "Action/Agent"
    category = ENodeCategory.ACTION
    displayName = "Agent"
    description = "调用完整 ReAct Agent（工具/技能/MCP），返回生成文本"

    def __init__(self, **config) -> None:
        super().__init__(**config)
        self._agent: Agent | None = None
        self._agentModelName: str | None = None

    @classmethod
    def GetConfigSchema(cls) -> list[dict]:
        return [
            {"name": "ModelName", "type": "string", "default": "", "description": "模型名称（空=默认）"},
            {"name": "SystemPrompt", "type": "string", "default": "", "description": "系统提示词"},
            {"name": "UserMessage", "type": "string", "default": "", "description": "首轮用户消息（无上游时）"},
            {"name": "Temperature", "type": "number", "default": 0.7, "description": "采样温度（0-2），越高越随机"},
            {"name": "EnableThinking", "type": "boolean", "default": False, "description": "是否开启思考链"},
        ]

    @handler
    async def Handle(self, message: WorkflowMessage) -> None:
        """默认入口：接收 WorkflowMessage，提取 content 作为用户消息。"""
        userMessage = message.message or getattr(self, "UserMessage", "") or "hello"
        systemPrompt = getattr(self, "SystemPrompt", "") or ""
        await self._CallAgentAsync(systemPrompt, userMessage)

    @handler(inputType=dict)
    async def HandleDict(self, message: dict) -> None:
        content = message.get("content") or message.get("userMessage") or "hello"
        systemPrompt = message.get("systemPrompt") or getattr(self, "SystemPrompt", "") or ""
        await self._CallAgentAsync(systemPrompt, content)

    @handler(inputType=str)
    async def HandleStr(self, message: str) -> None:
        systemPrompt = getattr(self, "SystemPrompt", "") or ""
        await self._CallAgentAsync(systemPrompt, message)

    async def _CallAgentAsync(self, systemPrompt: str, userMessage: str) -> None:
        """核心逻辑：通过 Agent 流式 ReAct 调用 LLM、写回上下文。"""
        modelName = getattr(self, "ModelName", "") or None
        temperature = float(getattr(self, "Temperature", 0.5) or 0.5)
        enableThinking = bool(getattr(self, "EnableThinking", False))

        # 按需创建 / 复用 Agent（modelName 变更时重建）
        if self._agent is None or self._agentModelName != modelName:
            self._agent = AgentManager.CreateSubAgent(modelName)
            self._agentModelName = modelName
            # 注入 SystemPrompt 为 SYSTEM 角色消息（而非拼入 userMessage）
            if systemPrompt:
                ctxComp = self._agent.GetComponent(ContextComponent)
                ctxComp.Ingest(ERole.SYSTEM, systemPrompt, lodLevel=EContextLodLevel.SUMMARIZABLE)

        llmComp = self._agent.GetComponent(LLMComponent)
        llmComp.RequestParams.temperature = temperature
        llmComp.RequestParams.enableThinking = enableThinking

        self._streamNodeId = self.context.CurrentNodeId
        self._streamExecutionRound = self.context.ExecutionRound
        self._streamEnableThinking = enableThinking
        self._streamFullContent = ""

        eventBusComp = self._agent.GetComponent(EventBusComponent)
        eventBusComp.AddListener(self._OnAgentStreamEvent)

        try:
            await self._agent.RunAsync(userMessage, self.context.CancellationToken, stream=True)
        finally:
            eventBusComp.RemoveListener(self._OnAgentStreamEvent)

        if llmComp.TotalPromptTokens > 0:
            self._streamFullContent += f"\ntokens: in{llmComp.TotalPromptTokens} out{llmComp.TotalCompletionTokens}"

        self.context.Set(f"{self._streamNodeId}.Response", self._streamFullContent)

        await self.context.SendMessageAsync(WorkflowMessage(
            nodeId=self._streamNodeId,
            message=self._streamFullContent,
        ))

    def _OnAgentStreamEvent(self, event: AgentStreamEvent) -> None:
        """Agent 流式事件回调：监听 Complete 事件，推送完整文本到工作流事件总线。"""
        from task.workflow.core.workflowEventData import EWorkflowEventType, WorkFlowEventData
        from task.workflow.core.baseNode import ENodeStatus

        ctx = self.context
        if ctx is None:
            return
        if event.eventType == EAgentStreamEventType.TEXT_COMPLETE:
            self._streamFullContent = event.content
            ctx.PushProgress(WorkFlowEventData(
                type=EWorkflowEventType.AI_CONTENT,
                nodeId=self._streamNodeId,
                agentId=self._agent.agentId if self._agent else 0,
                message=event.content,
            ))
        elif event.eventType == EAgentStreamEventType.ERROR:
            ctx.PushProgress(WorkFlowEventData(
                type=EWorkflowEventType.NODE_STATUS,
                nodeId=self._streamNodeId,
                agentId=self._agent.agentId if self._agent else 0,
                message=event.content,
                status=ENodeStatus.FAILED,
            ))
