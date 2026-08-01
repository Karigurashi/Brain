"""WorkFlowEventData —— Workflow 进度事件载荷。"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from .baseNode import ENodeStatus


class EWorkflowEventType(IntEnum):
    """Workflow PROGRESS 事件的细分种类。"""

    FLOW_START = 0
    FLOW_DONE = 1
    FLOW_CANCEL = 2
    NODE_STATUS = 3
    AI_CONTENT = 4


@dataclass(slots=True)
class WorkFlowEventData:
    """Workflow 进度/流式数据。"""

    type: EWorkflowEventType
    nodeId: int = 0
    agentId: int = 0
    message: str = ""
    status: Optional[ENodeStatus] = field(default=None)

