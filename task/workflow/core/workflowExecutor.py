"""WorkflowExecutor —— MAF 风格的消息驱动执行引擎。

支持 CancellationToken 协作式取消：
- 入口时设入 WorkflowContext 供节点透传给 LLM
- 每个节点执行前检查取消令牌
- asyncio.CancelledError 触发时自动 Cancel Token 以通知底层 LLM 连接关闭
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

from .workflowContext import WorkflowContext
from .workflowMessage import WorkflowMessage
from .baseNode import ENodeStatus
from common.cancellationToken import CancellationToken
from .workflowEventData import EWorkflowEventType, WorkFlowEventData

if TYPE_CHECKING:
    from .baseNode import BaseNode
    from ..workflow import Workflow

MAX_EXECUTION_DEPTH = 5000


class WorkflowExecutor:
    """消息驱动执行引擎，沿有向边遍历图结构，通过 @handler 类型路由调用节点。

    用法::

        wf = Workflow.FromDict(jsonData)
        ctx = WorkflowContext()
        await WorkflowExecutor.ExecuteAsync(wf, ctx)
    """

    # ---- 公开接口 ----

    @staticmethod
    async def ExecuteAsync(
        workflow: "Workflow",
        ctx: WorkflowContext,
        cancellationToken: CancellationToken,
    ) -> WorkflowContext:
        """异步执行工作流，从入口节点开始消息驱动遍历。

        Args:
            workflow: 工作流定义，ctx 通过 workflow 获取 graph / eventBus / taskId。
            ctx: 共享上下文。
            cancellationToken: 取消令牌，支持协作式取消。
                asyncio.CancelledError 触发时自动 Cancel。

        Returns:
            执行后的 WorkflowContext，包含所有中间结果和输出。
        """
        ctx.SetCancellationToken(cancellationToken)
        ctx.SetWorkflow(workflow)

        # 通知：事件流开始
        ctx.PushProgress(WorkFlowEventData(type=EWorkflowEventType.FLOW_START))

        # 查找入口节点
        entryNodes = ctx.Graph.GetEntryNodes()
        if not entryNodes:
            raise RuntimeError(
                f"Workflow '{workflow.info.name}': no entry node found. "
                f"Add at least one Action node with no incoming edges."
            )

        # 从每个入口并发开始执行（初始消息为空 WorkflowMessage）
        tasks = [
            WorkflowExecutor._ExecuteNodeAsync(entryId, WorkflowMessage(nodeId=0, message=""), ctx)
            for entryId in entryNodes
        ]
        try:
            await asyncio.gather(*tasks)
            finalMessages = ctx.ConsumeMessages()
            text = ""
            if finalMessages:
                text = finalMessages[-1].message
            ctx.PushProgress(WorkFlowEventData(
                type=EWorkflowEventType.FLOW_DONE,
                message=text,
            ))
            return ctx
        except asyncio.CancelledError:
            # 任务被取消时：Cancel Token → 底层 LLM 连接关闭 → 推送 FLOW_CANCEL
            cancellationToken.Cancel()
            ctx.PushProgress(WorkFlowEventData(type=EWorkflowEventType.FLOW_CANCEL))
            raise
        except Exception:
            raise

    # ---- 内部执行逻辑 ----

    @staticmethod
    async def _ExecuteNodeAsync(
        nodeId: int,
        message: Any,
        ctx: WorkflowContext,
        depth: int = 0,
        consumeMessages: bool = True,
    ) -> None:
        """异步执行单个 BaseNode，沿边继续遍历下游。

        Args:
            nodeId: 当前节点 ID（int）。
            message: 上游传入的消息。
            ctx: 共享上下文（通过 ctx.Graph 获取图结构）。
            depth: 已废弃 —— 深度由 ctx.CurrentDepth 统一跟踪，供复合节点内嵌调用兼容保留。
            consumeMessages: 是否消费并路由子节点消息。
                Composite 节点执行子节点时传入 False，自行统一消费聚合。
        """
        executor = ctx.Graph.GetNode(nodeId)
        if executor is None:
            raise RuntimeError(f"Node '{nodeId}' not found in graph.")

        # 0. 检查取消令牌（节点执行前）
        if ctx.CancellationToken and ctx.CancellationToken.IsCancellationRequested:
            ctx.PushProgress(WorkFlowEventData(
                type=EWorkflowEventType.NODE_STATUS,
                nodeId=nodeId,
                status=ENodeStatus.CANCELLED,
            ))
            return

        # 1. 查找匹配的 @handler
        handlerFn = WorkflowExecutor._ResolveHandler(executor, message)
        if handlerFn is None:
            return

        # 1.5 进入节点执行：设置 CurrentNodeId，ExecutionRound +1，Depth +1
        ctx._BeginNodeExecution(nodeId)

        # 1.6 深度保护（_BeginNodeExecution 已将 ctx._currentDepth +1）
        if ctx.CurrentDepth > MAX_EXECUTION_DEPTH:
            ctx._EndNodeExecution()
            raise RecursionError(
                f"Workflow execution exceeded max depth {MAX_EXECUTION_DEPTH}. "
                f"Possible infinite loop at node '{nodeId}'."
            )

        # 2. 通知：节点开始执行
        ctx.PushProgress(WorkFlowEventData(
            type=EWorkflowEventType.NODE_STATUS,
            nodeId=nodeId,
                status=ENodeStatus.RUNNING,
        ))

        try:
            executor.context = ctx
            await handlerFn(executor, message)
            # 通知：节点执行完成
            ctx.PushProgress(WorkFlowEventData(
                type=EWorkflowEventType.NODE_STATUS,
                nodeId=nodeId,
                status=ENodeStatus.COMPLETED,
            ))
        finally:
            ctx._EndNodeExecution()

        # 4. 消费 ctx 中的待发送消息，路由到下游
        if consumeMessages:
            pendingMessages = ctx.ConsumeMessages()
            for msg in pendingMessages:
                if msg.targetIds:
                    targets = msg.targetIds
                else:
                    # 默认路由：所有 OUT 类型下游边指向的节点
                    targets = [e.toNodeId for e in ctx.Graph.GetOutEdgesFrom(nodeId)]

                if targets:
                    tasks = [
                        WorkflowExecutor._ExecuteNodeAsync(tid, msg, ctx)
                        for tid in targets
                    ]
                    await asyncio.gather(*tasks)
                else:
                    # 叶子节点消息，无下游路由 → 放回队列，由 finally 统一收集
                    ctx._pendingMessages.append(msg)

    @staticmethod
    def _ResolveHandler(executor: "BaseNode", message: Any) -> callable | None:
        """根据消息类型解析对应的 @handler 方法。

        Args:
            executor: BaseNode 实例。
            message: 上游传入的消息。

        Returns:
            匹配的 handler 方法，无匹配返回 None。
        """
        handlers = executor._GetHandlers()

        if not handlers:
            # 无 @handler：回退到 ExecuteAsync（兼容）
            if hasattr(executor, "ExecuteAsync"):
                return executor.ExecuteAsync
            return None

        # 只有一个 handler：直接返回
        if len(handlers) == 1:
            return next(iter(handlers.values()))

        # 多个 handler：按 input type 匹配
        if message is None:
            defaultHandler = handlers.get(type(None)) or handlers.get(None)
            if defaultHandler:
                return defaultHandler

        msgType = type(message)
        for inputType, handlerMethod in handlers.items():
            if inputType is not None and issubclass(msgType, inputType):
                return handlerMethod

        # 回退到默认 handler（@handler 无 inputType）
        if None in handlers:
            return handlers[None]

        return None
