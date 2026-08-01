"""Todo 条目数据类与状态枚举。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class ETodoStatus(str, Enum):
    """TODO 条目状态。使用 str 基类，值即为小写标识，与 LLM 读写对齐。"""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETE = "completed"
    CANCELLED = "cancelled"


@dataclass(slots=True)
class TodoItem:
    """TODO 条目，由 StatusBar 构造并管理。"""

    content: str
    status: ETodoStatus = ETodoStatus.PENDING
