"""ToolComponent —— Agent 工具调度与管理组件。

对标 Claude Code Tool 体系，提供：
    - ToolComponent: 工具管理组件（实现 IComponent），持有工具注册表与调度分发。
    - BaseTool: 工具抽象基类，声明 name/description/parameters + ExecuteAsync。
    - ToolResult: 统一执行结果封装。
    - EToolCategory: 工具分类枚举（File / Shell / Network / Knowledge / Agent / MCP / Custom）。
    - control/file/shell/network: 内置工具子包（按分类组织）。

外部扩展方式::

    from agent.tool import BaseTool, EToolCategory, ToolComponent

    # 方式一：装饰器注册
    @ToolComponent.Register
    class MyTool(BaseTool):
        name = "my_tool"
        description = "My custom tool"
        category = EToolCategory.CUSTOM
        parameters = {...}

        async def ExecuteAsync(self, **kwargs) -> ToolResult:
            ...

    # 方式二：实例注册
    toolComp = ToolComponent()
    toolComp.RegisterTool(myToolInstance)

    # 绑定到 LLM
    specs = toolComp.GetAllToolSpecs()
    llmClient.BindTools(specs)

    # 分发 LLM ToolCall
    result = await toolComp.DispatchAsync(toolCall)
"""

from .baseTool import BaseTool, EToolParallelMode
from .eToolCategory import EToolCategory
from .toolComponent import ToolComponent
from .toolResult import ToolResult

__all__ = [
    "BaseTool",
    "EToolCategory",
    "EToolParallelMode",
    "ToolComponent",
    "ToolResult",
]
