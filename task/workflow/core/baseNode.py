"""BaseNode 基类 —— MAF 风格的节点基类，支持 @handler 类型路由重载。

节点参数直接配置为实例属性，不再通过引脚传递数据。
子类通过 @handler 装饰器声明消息处理方法，执行引擎按类型路由。

上下文（WorkflowContext）由执行引擎在 handler 调用前自动注入到 ``self.context``，
handler 方法签名仅需 ``(self, message)``，无需手动传递 ctx。
"""

from __future__ import annotations

import inspect
from enum import IntEnum
from typing import TYPE_CHECKING, Any, Callable, Optional

if TYPE_CHECKING:
    from .workflowContext import WorkflowContext


# ---- 枚举: 节点分类 ----

class ENodeCategory(IntEnum):
    """节点二分类：Action（行为）、Composite（组合）。"""

    ACTION = 0
    COMPOSITE = 1


# ---- 枚举: 节点执行状态 ----

class ENodeStatus(IntEnum):
    """节点执行状态。

    Attributes:
        RUNNING: 节点正在执行。
        COMPLETED: 节点执行完成。
        FAILED: 节点执行失败。
        CANCELLED: 节点被取消。
    """

    RUNNING = 0
    COMPLETED = 1
    FAILED = 2
    CANCELLED = 3


# ---- handler 装饰器 ----

_HANDLER_ATTR = "_maf_handlers"


def handler(method: Callable | None = None, *, inputType: type | None = None) -> Callable:
    """标记方法为消息处理器（MAF @handler 风格）。

    ctx 已作为 ``self.context`` 注入节点实例，handler 无需接收 ctx 参数。

    支持两种用法::

        # 1. 无参数 —— 从类型注解自动推导 input type
        @handler
        async def HandleStr(self, message: str) -> None:
            ...

        # 2. 显式指定 input type
        @handler(inputType=int)
        async def HandleInt(self, message) -> None:
            ...

    若未指定 inputType，装饰器从方法的第二个参数（message）的类型注解推导。

    ctx 已通过 ``self.context`` 可用，无需在 handler 签名中声明。
    """

    def _Decorator(m: Callable) -> Callable:
        _SetHandlerMeta(m, inputType)
        return m

    if method is not None:
        return _Decorator(method)
    return _Decorator


def _SetHandlerMeta(method: Callable, inputType: type | None) -> None:
    """为方法打上 handler 元数据标记。"""
    if not hasattr(method, _HANDLER_ATTR):
        setattr(method, _HANDLER_ATTR, {})
    getattr(method, _HANDLER_ATTR)["inputType"] = inputType


def _GetHandlerInputType(method: Callable) -> type | None:
    """获取 handler 的 input type。"""
    meta = getattr(method, _HANDLER_ATTR, None)
    if meta and "inputType" in meta and meta["inputType"] is not None:
        return meta["inputType"]

    # 从类型注解推导
    hints = inspect.getfullargspec(method).annotations
    # 第二个参数是 message
    params = list(inspect.signature(method).parameters.keys())
    if len(params) >= 2:
        msgParam = params[1]
        if msgParam in hints:
            return hints[msgParam]
    return None


# ---- BaseNode 基类 ----

class BaseNode:
    """MAF 风格 BaseNode 基类 —— 所有工作流节点的基类。

    子类必须覆盖:
        - ``nodeType``: 类型标识，格式 ``"Category/Name"``。
        - ``category``: 节点分类枚举。
        - ``displayName``: 可视化展示名称。

    子类可选覆盖:
        - ``description``: 节点功能描述。
        - ``GetConfigSchema()``: 返回可配置参数 schema。
        - 一个或多个 ``@handler`` 方法。

    参数通过 ``__init__(**config)`` 直接配置为实例属性::

        delay = DelayNode(Duration=2.0)
        print(delay.Duration)  # 2.0

    上下文通过 ``self.context`` 访问::

        @handler
        async def Handle(self, message: WorkflowMessage) -> None:
            await self.context.SendMessageAsync(message)
    """

    nodeType: str = ""
    """节点类型标识，格式 ``"Category/Name"``。"""

    category: ENodeCategory | None = None
    """节点所属分类。"""

    displayName: str = ""
    """可视化展示名称。"""

    description: str = ""
    """节点功能描述。"""

    x: float = 0.0
    """节点在画布中的 X 坐标，由 WorkflowGraph.AddNode/AddNodeAuto 写入。"""

    y: float = 0.0
    """节点在画布中的 Y 坐标，由 WorkflowGraph.AddNode/AddNodeAuto 写入。"""

    name: str | None = None
    """用户自定义节点名称，None 则使用 displayName。

    通过 ``__init__(name="MyNode", ...)`` 设置，或在前端属性面板中编辑。
    """

    context: Optional[WorkflowContext] = None
    """执行上下文，由 WorkflowExecutor 在 handler 调用前注入。

    handler 方法中通过 ``self.context`` 访问，无需作为参数传递。
    """

    _handlersCache: dict[type | None, Callable] | None = None
    """类级 handler 缓存，_GetHandlers() 首次调用后填充，避免每次执行的反射扫描。"""

    def __init__(self, **config: Any) -> None:
        """初始化节点实例，参数直接设置为实例属性。

        Args:
            **config: 节点可配置参数，如 ``Duration=1.0``、``SystemPrompt="You are..."``。
        """
        for key, value in config.items():
            setattr(self, key, value)

    # ---- 子类覆盖: 配置 Schema ----

    @classmethod
    def GetConfigSchema(cls) -> list[dict[str, Any]]:
        """返回可配置参数 schema 列表，供前端面板渲染。

        每项格式::

            {
                "name": "Duration",
                "type": "float",
                "default": 1.0,
                "description": "延迟秒数",
            }

        Returns:
            配置参数描述列表。
        """
        return []

    # ---- 子类覆盖: handler 方法 ----

    @classmethod
    def _GetHandlers(cls) -> dict[type | None, Callable]:
        """获取所有 @handler 方法，按 input type 索引（类级缓存，避免每次执行反射扫描）。

        Returns:
            ``{inputType: handlerMethod}`` 字典，key 为 None 表示默认 handler。
        """
        if cls._handlersCache is not None:
            return cls._handlersCache

        handlers: dict[type | None, Callable] = {}
        for name in dir(cls):
            if name.startswith("_"):
                continue
            attr = getattr(cls, name, None)
            if not callable(attr):
                continue
            if hasattr(attr, _HANDLER_ATTR):
                inputType = _GetHandlerInputType(attr)
                handlers[inputType] = attr

        cls._handlersCache = handlers
        return handlers

    # ---- 可视化元数据 ----

    @classmethod
    def GetNodeInfo(cls) -> dict[str, Any]:
        """返回节点元数据，供可视化工具检索。"""
        return {
            "nodeType": cls.nodeType,
            "category": cls.category.name if cls.category else "",
            "displayName": cls.displayName,
            "description": cls.description,
            "configSchema": cls.GetConfigSchema(),
        }
