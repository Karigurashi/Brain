"""工具抽象基类 —— 所有工具必须继承此基类。

对标 Claude Code Tool 体系 + LangChain BaseTool：
- 静态声明 name / description / parameters（LLM function calling 规格）。
- _Invoke() 同步执行逻辑（子类覆盖）。
- _InvokeAsync() 异步执行逻辑（可选覆盖，默认回退 _Invoke）。
- ExecuteAsync() 公共异步入口，统一对外接口。
"""

from __future__ import annotations

from abc import ABC
from enum import IntEnum
from typing import Any, TYPE_CHECKING

from llm.provider.chatMessage import ToolSpec

from agent.component.contex.eContextLodLevel import EContextLodLevel

from .eToolCategory import EToolCategory
from .toolResult import ToolResult


class EToolParallelMode(IntEnum):
    """工具并行调度模式。每个工具声明自身的并行安全级别。"""

    SERIAL = 0   # 保守串行：shell、副作用工具、未审查工具（默认）
    SAFE = 1     # 安全并发：只读工具（grep、webFetch 等）
    PATH = 2     # 路径作用域：同文件路径冲突时串行，否则可并发（read、write 等）

if TYPE_CHECKING:
    from agent.core.baseAgent import BaseAgent


class BaseTool(ABC):
    """工具抽象基类 —— 子类覆盖类属性声明元数据，实现 _Invoke / _InvokeAsync 定义行为。

    执行模式（双轨制）::

        _Invoke(**kwargs)   → 同步主逻辑（纯同步操作如文件读写实现此方法）
        _InvokeAsync(**kwargs)  → 异步逻辑（默认回退到 _Invoke，异步操作如 subprocess 覆盖此方法）
        ExecuteAsync(**kwargs) → 公共异步入口，始终可用

    子类必须覆盖:
        - ``name``: 工具名称（LLM function name）。
        - ``description``: 工具描述。
        - ``parameters``: JSON Schema 参数定义。
        - ``category``: 工具分类枚举。
        - ``_Invoke()``: 同步执行逻辑（返回 ToolResult）。

    Example::

        @ToolComponent.Register
        class ReadFileTool(BaseTool):
            name = "read_file"
            description = "Read the contents of a file"
            category = EToolCategory.FILE
            parameters = {
                "type": "object",
                "properties": {
                    "filePath": {"type": "string", "description": "..."},
                },
                "required": ["filePath"],
            }

            def _Invoke(self, filePath: str) -> ToolResult:
                with open(filePath, "r") as f:
                    content = f.read()
                return ToolResult.Ok(content, toolName=self.name)
    """

    # ---- 子类覆盖: 元数据 ----

    name: str = ""
    """工具名称，作为 LLM function name。"""

    description: str = ""
    """工具描述，LLM 据此判断调用时机。"""

    category: EToolCategory = EToolCategory.CUSTOM
    """工具所属分类。"""

    parameters: dict[str, Any] = {}
    """JSON Schema 格式的参数定义。"""

    timeout: float | None = None
    """工具执行超时秒数，None 表示不设限制。子类可覆盖此值。

    例如：文件读取 30s、网络请求 60s、Shell 命令 300s。
    """

    resultLodLevel: EContextLodLevel | None = EContextLodLevel.DISCARDABLE
    """工具结果注入上下文的 LOD 等级，默认 DISCARDABLE（可压缩可丢弃）。

    子类覆盖以控制结果持久化策略：
    - SUMMARIZABLE (LOD1)：可压缩不可丢弃（如 Skill 工具返回的 SOP）。
    - DISCARDABLE (LOD2)：可压缩可丢弃（旧工具结果，默认值）。
    - EXTERNAL_ONLY (LOD4)：当轮注入、次轮丢弃。
    - LATEST_ONLY (LOD3)：卸载时只留最后 1 条。
    """

    skipPersist: bool = False
    """是否跳过大结果落盘。子类覆盖为 True 表示结果已在磁盘上无需二次落盘。

    例如：read_file 读取的文件本身已在磁盘，不需要再写入 ContentStore。
    """

    countCalls: bool = True
    """是否计入调用次数统计，默认 True。子类覆盖为 False 可排除计数。"""

    # ---- 子类覆盖: 并行调度模式 ----

    parallelMode: EToolParallelMode = EToolParallelMode.SERIAL
    """并行调度模式。SERIAL=保守串行, SAFE=安全并发, PATH=路径作用域。"""

    _agent: BaseAgent | None = None
    """ToolComponent 在调度前自动注入的 Agent 引用。

    工具可在 _Invoke / _InvokeAsync 中通过 self._agent 获取当前 Agent 实例，
    进而通过 GetComponent() 访问其他组件（如 Session、Context、EventPush 等）。
    无需子类声明此字段。
    """

    _cachedToolSpec: ToolSpec | None = None
    """ToolSpec 类级缓存，避免每轮 ReAct 重复分配。

    name/description/parameters 均为类级常量，运行时不可变，安全缓存。
    首次 ToToolSpec() 调用后填充，后续直接返回缓存实例。
    """

    # ---- 子类覆盖: 执行逻辑 ----

    def _Invoke(self, **kwargs) -> ToolResult:
        """同步执行逻辑 —— 子类覆盖此方法实现纯同步操作。

        文件读写、内存计算等操作仅需实现此方法。
        返回值自动被 _InvokeAsync 在线程池中异步包装。

        Args:
            **kwargs: 与 parameters 定义对应的关键字参数。

        Returns:
            ToolResult: 统一执行结果。

        Raises:
            NotImplementedError: 子类未实现 _Invoke 或 _InvokeAsync。
        """
        raise NotImplementedError(
            f"{self.__class__.__name__}: must implement _Invoke() or _InvokeAsync()"
        )

    async def _InvokeAsync(self, **kwargs) -> ToolResult:
        """异步执行逻辑 —— 默认回退到 _Invoke。

        异步操作（subprocess、网络请求等）覆盖此方法避免阻塞事件循环。
        默认实现在线程池中执行 _Invoke，保证 ExecuteAsync 始终异步兼容。

        Args:
            **kwargs: 与 parameters 定义对应的关键字参数。

        Returns:
            ToolResult: 统一执行结果。
        """
        import asyncio
        return await asyncio.to_thread(self._Invoke, **kwargs)

    async def ExecuteAsync(self, **kwargs) -> ToolResult:
        """公共异步执行入口 —— 优先 _InvokeAsync，回退 _Invoke。

        外部只需调用此方法，无需关心底层是同步还是异步实现。

        Args:
            **kwargs: 与 parameters 定义对应的关键字参数。

        Returns:
            ToolResult: 统一执行结果。
        """
        return await self._InvokeAsync(**kwargs)

    # ---- LLM 工具描述转换 ----

    def ToToolSpec(self) -> ToolSpec:
        """转换为 LLM 统一工具描述（ToolSpec），首次调用后类级缓存。

        Returns:
            ToolSpec 对象，可直接传给 LLMClient.BindTools()。
        """
        cls = type(self)
        if cls._cachedToolSpec is None:
            cls._cachedToolSpec = ToolSpec(
                name=self.name,
                description=self.description,
                parameters=self.parameters,
            )
        return cls._cachedToolSpec

    @classmethod
    def GetToolInfo(cls) -> dict[str, Any]:
        """返回工具元数据，供外部检索和可视化。"""
        return {
            "name": cls.name,
            "description": cls.description,
            "category": cls.category.value,
            "parameters": cls.parameters,
        }

    # ---- 生命周期钩子 ----

    def OnDestroy(self) -> None:
        """工具被卸载时的清理回调，子类覆盖以释放资源。

        例如 ShellTool 覆盖此方法 kill 残留后台进程。
        """
        pass