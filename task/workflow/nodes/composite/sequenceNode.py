"""序列/顺序节点 —— 链式执行子节点，前一子节点产出作为后一子节点输入，仅末尾子节点结果向下游广播。"""

from ...core.baseNode import BaseNode, ENodeCategory, handler
from ...core.nodeRegistry import NodeRegistry
from ...core.workflowExecutor import WorkflowExecutor
from ...core.workflowMessage import WorkflowMessage


@NodeRegistry.Register
class SequenceNode(BaseNode):
    """链式顺序执行 —— 子节点串行，前置产出链入后置输入，仅末尾子节点结果向下游广播。

    Config: 无。
    """

    nodeType = "Composite/Sequence"
    category = ENodeCategory.COMPOSITE
    displayName = "Sequence"
    description = "链式顺序执行 —— 子节点串行，前置产出链入后置输入，仅末尾子节点结果向下游广播"

    @classmethod
    def GetConfigSchema(cls) -> list[dict]:
        return []

    @handler
    async def Handle(self, message: WorkflowMessage) -> None:
        """链式执行子节点，前置产出作为后置输入，仅末尾子节点最终消息向下游广播。"""
        graph = self.context.Graph
        subEdges = graph.GetSubNodeEdgesFrom(self.context.CurrentNodeId)
        if not subEdges:
            await self.context.SendMessageAsync(message)
            return

        # 链式传递：当前输入从入口消息开始，每轮迭代替换为上一子节点的产出
        currentInput = message
        for edge in subEdges:
            await WorkflowExecutor._ExecuteNodeAsync(
                edge.toNodeId, currentInput, self.context,
                consumeMessages=False,
            )
            # 消费子节点产生的消息，取最后一条作为下一子节点的输入
            childMessages = self.context.ConsumeMessages()
            if childMessages:
                currentInput = childMessages[-1]

        # 仅将末尾子节点的最终消息向下游广播
        if len(subEdges) > 0 and currentInput is not message:
            await self.context.SendMessageAsync(WorkflowMessage(
                nodeId=self.context.CurrentNodeId,
                message=currentInput.message,
            ))
