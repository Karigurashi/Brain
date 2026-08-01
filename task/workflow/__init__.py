"""Workflow —— 基于 MAF (Microsoft Agent Framework) 风格的可视化工作流执行框架。

核心设计：
    - BaseNode 节点实例，参数直配为属性，无引脚。
    - @handler 装饰器支持类型路由重载。
    - WorkflowContext 承载运行时消息传递与变量存储。
    - WorkflowEdge 节点级有向边（node-to-node）。
    - WorkflowGraph + WorkflowExecutor 图结构 + 消息驱动执行。
    - NodeRegistry 全局注册表 + 装饰器注册，支持外部扩展。
"""

from .workflow import Workflow
from .workflowResult import WorkflowResult
from .core.baseNode import BaseNode, ENodeCategory, handler
from .core.workflowContext import WorkflowContext
from .core.workflowEdge import WorkflowEdge, EEdgeType
from .core.workflowGraph import WorkflowGraph
from .core.workflowExecutor import WorkflowExecutor
from .core.workflowMessage import WorkflowMessage
from .core.nodeRegistry import NodeRegistry

# 导入所有内置节点以触发注册
from .nodes import action as _action_nodes
from .nodes import composite as _composite_nodes

__all__ = [
    "Workflow",
    "WorkflowResult",
    "BaseNode",
    "handler",
    "WorkflowContext",
    "WorkflowEdge",
    "EEdgeType",
    "WorkflowGraph",
    "WorkflowExecutor",
    "WorkflowMessage",
    "ENodeCategory",
    "NodeRegistry",
]
