"""WorkflowContext —— MAF 风格的类型安全执行上下文，替代 Blackboard。

提供消息传递（SendMessageAsync）和 KV 变量存储，
以及 CancellationToken 取消令牌传递。

Graph、EventBus、WorkflowId 等通过 ``self._workflow`` 透传，
不再在 Context 中冗余存储。
"""

from __future__ import annotations

from typing import Any, Optional, TYPE_CHECKING

from .workflowMessage import WorkflowMessage

if TYPE_CHECKING:
    from common.cancellationToken import CancellationToken
    from ..workflow import Workflow
    from .workflowEventData import WorkFlowEventData
    from .workflowGraph import WorkflowGraph


class WorkflowContext:
    """MAF 风格的 WorkflowContext，承载工作流执行期间的运行时状态。

    用法::

        ctx = WorkflowContext()
        ctx.Set("var.Count", 0)
        await ctx.SendMessageAsync({"text": "hello"})

    节点可通过 ctx.CancellationToken 获取取消令牌并透传给 LLM 调用。
    流式事件通过 ctx.PushProgress() 同步推送到 Workflow 注入的 sink。
    """

    def __init__(self, initialData: dict[str, Any] | None = None) -> None:
        self._data: dict[str, Any] = initialData.copy() if initialData else {}
        self._pendingMessages: list[WorkflowMessage] = []
        self._workflow: Optional["Workflow"] = None
        self._cancellationToken: Optional["CancellationToken"] = None
        self._currentNodeId: int = 0
        self._executionRound: int = 0
        self._currentDepth: int = 0

    # ---- KV 存储 ----

    def Get(self, key: str, default: Any = None) -> Any:
        """读取键值。"""
        return self._data.get(key, default)

    def Set(self, key: str, value: Any) -> None:
        """写入键值。"""
        self._data[key] = value

    def Has(self, key: str) -> bool:
        """检查键是否存在。"""
        return key in self._data

    def Remove(self, key: str) -> None:
        """删除键。"""
        self._data.pop(key, None)

    def GetAll(self) -> dict[str, Any]:
        """返回所有数据的浅拷贝。"""
        return dict(self._data)

    def Merge(self, other: dict[str, Any]) -> None:
        """批量合并数据。"""
        self._data.update(other)

    # ---- 消息传递 ----

    async def SendMessageAsync(self, message: WorkflowMessage) -> None:
        """向下游节点发送消息。

        Args:
            message: 要发送的 WorkflowMessage。
        """
        self._pendingMessages.append(message)

    def ConsumeMessages(self) -> list[WorkflowMessage]:
        """消费所有待发送消息（执行引擎使用）。"""
        messages = self._pendingMessages
        self._pendingMessages = []
        return messages

    # ---- 取消令牌 ----

    @property
    def CancellationToken(self) -> Optional["CancellationToken"]:
        """当前工作流的取消令牌，节点可用此令牌中断 LLM 调用。

        由 WorkflowExecutor 在执行前注入。
        """
        return self._cancellationToken

    def SetCancellationToken(self, token: "CancellationToken") -> None:
        """注入取消令牌（仅 WorkflowExecutor 调用）。"""
        self._cancellationToken = token

    # ---- Workflow 引用 ----

    def SetWorkflow(self, workflow: "Workflow") -> None:
        """注入 Workflow 引用，替代逐个 Set（仅 WorkflowExecutor 调用）。"""
        self._workflow = workflow

    # ---- 图引用 ----

    @property
    def Graph(self) -> Optional["WorkflowGraph"]:
        """当前执行的 WorkflowGraph，透传自 Workflow.graph。"""
        return self._workflow.graph if self._workflow else None

    # ---- 事件推送 ----

    def PushProgress(self, data: WorkFlowEventData) -> None:
        """推送进度/流式事件至 Workflow 的事件总线。"""
        if self._workflow is None:
            return
        self._workflow._PushProgress(data)

    @property
    def WorkflowId(self) -> int:
        """当前所属工作流 ID，透传自 Workflow.taskId。"""
        return self._workflow.info.taskId if self._workflow else 0

    # ---- 运行时状态 ----

    @property
    def CurrentNodeId(self) -> int:
        """当前正在执行的节点 ID（由 WorkflowExecutor 在执行前设置）。"""
        return self._currentNodeId

    @property
    def ExecutionRound(self) -> int:
        """当前执行轮次（任意节点每执行一次 +1）。"""
        return self._executionRound

    @property
    def CurrentDepth(self) -> int:
        """当前执行深度（每进入子节点 +1，退出 -1），用于防止无限嵌套。"""
        return self._currentDepth

    def _BeginNodeExecution(self, nodeId: int) -> int:
        """进入节点执行：设置当前节点 ID，全局轮次 +1，深度 +1（仅 WorkflowExecutor 调用）。"""
        self._currentNodeId = nodeId
        self._executionRound += 1
        self._currentDepth += 1
        return self._executionRound

    def _EndNodeExecution(self) -> None:
        """退出节点执行：深度 -1（仅 WorkflowExecutor 调用）。"""
        self._currentDepth -= 1
