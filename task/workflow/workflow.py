"""Workflow —— 工作流定义，封装图结构及运行时执行逻辑。"""

from __future__ import annotations

from typing import Any, Callable, Optional

from common.cancellationToken import CancellationToken
from common.syncEventBus import SyncEventBus
from .core.workflowContext import WorkflowContext
from .core.workflowEventData import WorkFlowEventData
from .core.workflowExecutor import WorkflowExecutor
from .core.workflowGraph import WorkflowGraph
from .workflowResult import WorkflowResult


class Workflow:
    """工作流定义 —— 由名称和图结构组成。

    不继承 Task，由 WorkflowComponent 提交时包装为 TaskT。

    Attributes:
        name: 工作流名称。
        graph: 图结构（BaseNode + Edge）。
        context: 运行时上下文。
    """

    def __init__(self, name: str = "") -> None:
        self.name: str = name or "Unnamed"
        self.graph = WorkflowGraph()
        self.context = WorkflowContext()
        self._progressBus: SyncEventBus[WorkFlowEventData] = SyncEventBus()

    def AddProgressListener(self, callback: Callable[[WorkFlowEventData], None]) -> None:
        """注册 Workflow 进度监听器。"""
        self._progressBus.AddListener(callback)

    def RemoveProgressListener(self, callback: Callable[[WorkFlowEventData], None]) -> None:
        """移除 Workflow 进度监听器。"""
        self._progressBus.RemoveListener(callback)

    async def ExecuteAsync(
        self,
        cancellationToken: Optional[CancellationToken] = None,
    ) -> WorkflowResult:
        """异步执行此工作流，返回包含统计和事件的 WorkflowResult。"""
        if cancellationToken is None:
            cancellationToken = CancellationToken()

        events: list[WorkFlowEventData] = []

        def _Collect(data: WorkFlowEventData) -> None:
            events.append(data)

        self._progressBus.AddListener(_Collect)
        try:
            self.context = WorkflowContext()
            ctx = await WorkflowExecutor.ExecuteAsync(
                self,
                self.context,
                cancellationToken,
            )
            return WorkflowResult(
                nodeCount=self.graph.NodeCount,
                round=ctx.ExecutionRound,
                events=events,
            )
        finally:
            self._progressBus.RemoveListener(_Collect)

    def _PushProgress(self, data: WorkFlowEventData) -> None:
        self._progressBus.Push(data)

    # ---- 序列化（委托 WorkflowSerializer） ----

    @classmethod
    def FromDict(cls, data: dict) -> "Workflow":
        from .core.workflowSerializer import WorkflowSerializer
        return WorkflowSerializer.FromDict(data)

    @classmethod
    def FromJson(cls, jsonStr: str) -> "Workflow":
        from .core.workflowSerializer import WorkflowSerializer
        return WorkflowSerializer.FromJson(jsonStr)

    def ToDict(self) -> dict[str, Any]:
        from .core.workflowSerializer import WorkflowSerializer
        return WorkflowSerializer.ToDict(self)

    def ToJson(self, indent: int = 2) -> str:
        from .core.workflowSerializer import WorkflowSerializer
        return WorkflowSerializer.ToJson(self, indent)
