"""WorkflowResult —— 执行结果对象，承载统计、事件、持久化。"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field

from common.serializeUtil import SerializeUtil
from .core.workflowEventData import EWorkflowEventType, WorkFlowEventData


@dataclass
class WorkflowResult:
    """Workflow 执行结果，包含统计信息和所有进度事件。"""

    nodeCount: int
    round: int
    events: list[WorkFlowEventData] = field(default_factory=list)

    @property
    def IsSuccess(self) -> bool:
        return True

    def GetLastEventMessage(self) -> str:
        """获取最后一个 FLOW_DONE 事件的消息文本。"""
        for ev in reversed(self.events):
            if ev.type == EWorkflowEventType.FLOW_DONE and ev.message:
                return ev.message
        return ""

    def ToJson(self, indent: int = 2) -> str:
        """导出为 JSON 字符串。"""
        return json.dumps({
            "nodeCount": self.nodeCount,
            "round": self.round,
            "events": [SerializeUtil.ToDict(ev) for ev in self.events],
            "result": self.GetLastEventMessage(),
            "isSuccess": self.IsSuccess,
        }, indent=indent, ensure_ascii=False)
