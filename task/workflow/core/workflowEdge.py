"""工作流边类型枚举与节点间有向边数据类。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum


class EEdgeType(IntEnum):
    """边类型：OUT（常规流程边，0）、CHILD（父节点到子节点的边，1）。"""

    OUT = 0
    CHILD = 1


@dataclass(slots=True)
class WorkflowEdge:
    """节点间有向边，表达从源节点到目标节点的连接。

    与 MAF Edge 对齐：不再有引脚名，边直接连接两个 BaseNode。

    Attributes:
        fromNodeId: 源节点 ID（int）。
        toNodeId: 目标节点 ID（int）。
        edgeType: 边类型 int 值（0=OUT 常规流程边，1=CHILD 父到子节点的边）。
    """

    fromNodeId: int
    toNodeId: int
    edgeType: int = EEdgeType.OUT
