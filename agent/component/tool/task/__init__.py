"""Task 工具 —— 定时任务与 Workflow（均为 Task 子系统）。"""

from .createScheduleTaskTool import CreateScheduleTaskTool
from .deleteTaskTool import DeleteTaskTool
from .runFlowTaskTool import RunFlowTaskTool
from .getFlowSchemaTool import GetFlowSchemaTool
from .listTasksTool import ListTasksTool

# enableWorkflow 开关控制的工具名（同属 TASK 分类，需按名启停）
WORKFLOW_TOOL_NAMES: tuple[str, ...] = (
    "runFlowTask",
    "deleteTask",
    "getFlowSchema",
)

# enableSchedule 开关控制的工具名
SCHEDULE_TOOL_NAMES: tuple[str, ...] = (
    "createScheduleTask",
    "deleteTask",
)

__all__ = [
    "CreateScheduleTaskTool",
    "DeleteTaskTool",
    "RunFlowTaskTool",
    "GetFlowSchemaTool",
    "ListTasksTool",
    "WORKFLOW_TOOL_NAMES",
    "SCHEDULE_TOOL_NAMES",
]
