"""工作流节点间消息数据类。

WorkflowMessage 是节点间唯一的消息载体，通过 SendMessageAsync 在下游传递，
最终由 WorkflowExecutor 路由或产出。
"""

from dataclasses import dataclass, field


@dataclass(slots=True)
class WorkflowMessage:
    """节点间消息 —— slots=True 节省内存，nodeId + content 最小契约。

    Attributes:
        nodeId: 发送消息的节点 ID（int）。
        message: 消息文本内容。
        targetIds: 目标节点 ID 列表，None 表示广播到所有下游（由 Executor 设置）。
    """

    nodeId: int
    message: str = ""
    targetIds: list[int] | None = field(default=None)
