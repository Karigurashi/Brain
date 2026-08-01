"""全局常量定义，项目内所有模块统一引用。"""

from enum import StrEnum


class ERole(StrEnum):
    """LLM 消息角色枚举，可替代字符串直接使用。

    Attributes:
        SYSTEM: 系统指令。
        USER: 用户输入。
        ASSISTANT: 模型回复。
        TOOL: 工具执行结果。
    """

    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class ERoad(StrEnum):
    """项目关键路径枚举，成员值可通过 / 操作符拼接子路径。"""

   
    SETTINGS_JSON = "settings.json"

    WORKSPACE = "workspace"
    MEMORY_DIR = "memory"
    STORE_DIR = ".store"
    SUBAGENT_DIR = "subagent"
    SKILLS_DIR = "skills"
    RULES_DIR = "rules"
    TASKS_DIR = "tasks"
    MANGO_IGNORE = ".mangoIgnore"
    MCP_JSON_PATH = ".mcp.json"
