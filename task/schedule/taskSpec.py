"""TaskSpec —— 可离线持久化的定时任务定义（与运行时 Task 分离）。"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class TaskSpec:
    """定时任务的静态定义，写入 schedules.json。

    Attributes:
        specId: 稳定自增 ID，重启后不变（区别于运行时 taskId）。
        name: 任务名称。
        expression: 5 字段 cron 表达式。
        prompt: 注入 Agent 的指令文本。
        createdAt: 创建时间戳。
        lastFiredAt: 上次触发时间戳。
        fireCount: 累计触发次数。
    """

    specId: int
    name: str = ""
    expression: str = ""
    prompt: str = ""
    createdAt: float = 0.0
    lastFiredAt: float = 0.0
    fireCount: int = 0
