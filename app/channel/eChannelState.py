"""Channel 状态机枚举 —— 控制 Channel 运行时的状态迁移。"""

from enum import IntEnum


class EChannelState(IntEnum):
    """Channel 运行时状态。

    Attributes:
        STOPPED: 已停止 / 未启动。
        STARTING: 启动中，正在执行 OnStartAsync。
        RUNNING: 运行中，可接收消息。
        STOPPING: 停止中，正在销毁群组并执行 OnStopAsync。
        ERROR: 异常终止。
    """

    STOPPED = 0
    STARTING = 1
    RUNNING = 2
    STOPPING = 3
    ERROR = 4
