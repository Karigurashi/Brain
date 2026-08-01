"""并行节点 —— 并行执行所有子节点，全部完成后向下游广播。"""

import asyncio

from ...core.baseNode import BaseNode, ENodeCategory, handler
from ...core.nodeRegistry import NodeRegistry
from ...core.workflowExecutor import WorkflowExecutor
from ...core.workflowMessage import WorkflowMessage


@NodeRegistry.Register
class ParallelNode(BaseNode):
    """并行执行 —— 并行执行所有子节点，全部完成后继续。

    Config: 无。
    """

    nodeType = "Composite/Parallel"
    category = ENodeCategory.COMPOSITE
    displayName = "Parallel"
    description = "并行执行所有子节点，全部完成后继续"

    @classmethod
    def GetConfigSchema(cls) -> list[dict]:
        return []

    @handler
    async def Handle(self, message: WorkflowMessage) -> None:
        """并行执行所有子节点，消费子消息后合并 content 向下游推送。"""
        graph = self.context.Graph
        if graph is None:
            await self.context.SendMessageAsync(message)
            return

        subEdges = graph.GetSubNodeEdgesFrom(self.context.CurrentNodeId)
        if not subEdges:
            await self.context.SendMessageAsync(message)
            return

        tasks = [
            WorkflowExecutor._ExecuteNodeAsync(
                edge.toNodeId, message, self.context,
                consumeMessages=False,
            )
            for edge in subEdges
        ]
        await asyncio.gather(*tasks)

        # 消费所有子节点写入的待发送消息，合并 content
        mergedParts: list[str] = []
        for msg in self.context.ConsumeMessages():
            if msg.message:
                node = graph.GetNode(msg.nodeId)
                label = node.name if (node and node.name) else (
                    node.displayName if node else f"Node {msg.nodeId}"
                )
                mergedParts.append(f"[{label}]{msg.message}")

        await self.context.SendMessageAsync(WorkflowMessage(
            nodeId=self.context.CurrentNodeId,
            message="\n".join(mergedParts),
        ))
