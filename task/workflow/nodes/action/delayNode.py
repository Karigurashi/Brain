"""延迟节点 —— 异步等待指定秒数后继续执行，不阻塞事件循环。"""

import asyncio

from ...core.baseNode import BaseNode, ENodeCategory, handler
from ...core.nodeRegistry import NodeRegistry
from ...core.workflowMessage import WorkflowMessage


@NodeRegistry.Register
class DelayNode(BaseNode):
    """延迟 —— 异步等待指定秒数（不阻塞事件循环）。

    Config:
        Duration: 延迟秒数（float，默认 1.0）。
    """

    nodeType = "Action/Delay"
    category = ENodeCategory.ACTION
    displayName = "Delay"
    description = "延迟指定秒数后继续执行"

    @classmethod
    def GetConfigSchema(cls) -> list[dict]:
        return [
            {"name": "Duration", "type": "float", "default": 1.0, "description": "延迟秒数"},
        ]

    @handler
    async def Handle(self, message: WorkflowMessage) -> None:
        duration = float(getattr(self, "Duration", 1.0))
        await asyncio.sleep(max(0.0, duration))
        await self.context.SendMessageAsync(message)
