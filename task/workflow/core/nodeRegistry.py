"""全局节点注册表 —— 管理所有 BaseNode 类型，支持装饰器注册和可视化检索。"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .baseNode import BaseNode, ENodeCategory


class NodeRegistry:
    """全局单例注册表，按 ``"Category/Name"`` 字符串索引所有 BaseNode 类。

    用法::

        from task.workflow.core.nodeRegistry import NodeRegistry

        @NodeRegistry.Register
        class MyNode(BaseNode):
            nodeType = "Action/MyNode"
            ...
    """

    _nodes: dict[str, type["BaseNode"]] = {}

    # ---- 注册 ----

    @classmethod
    def Register(cls, nodeClass: type["BaseNode"]) -> type["BaseNode"]:
        """装饰器：将 BaseNode 子类注册到全局表。"""
        nodeType = nodeClass.nodeType
        if not nodeType:
            raise ValueError(f"{nodeClass.__name__} must define a non-empty nodeType")
        cls._nodes[nodeType] = nodeClass
        return nodeClass

    @classmethod
    def Unregister(cls, nodeType: str) -> None:
        """移除注册。"""
        cls._nodes.pop(nodeType, None)

    # ---- 查询 ----

    @classmethod
    def Get(cls, nodeType: str) -> type["BaseNode"] | None:
        """按类型字符串获取 BaseNode 类。"""
        return cls._nodes.get(nodeType)

    @classmethod
    def GetAll(cls) -> dict[str, type["BaseNode"]]:
        """获取所有已注册类型。"""
        return dict(cls._nodes)

    @classmethod
    def GetByCategory(cls, category: "ENodeCategory") -> dict[str, type["BaseNode"]]:
        """按分类获取类型。"""
        return {
            k: v for k, v in cls._nodes.items() if v.category == category
        }

    # ---- 可视化 ----

    @classmethod
    def GetAllNodeInfo(cls) -> list[dict]:
        """返回所有节点元数据，供可视化工具展示节点列表。"""
        return [nodeClass.GetNodeInfo() for nodeClass in cls._nodes.values()]

    @classmethod
    def GetNodeInfoByCategory(cls, category: "ENodeCategory") -> list[dict]:
        """按分类返回节点元数据。"""
        return [
            nodeClass.GetNodeInfo()
            for nodeClass in cls._nodes.values()
            if nodeClass.category == category
        ]

    # ---- 管理 ----

    @classmethod
    def Count(cls) -> int:
        """已注册节点总数。"""
        return len(cls._nodes)

    @classmethod
    def Clear(cls) -> None:
        """清空所有注册。"""
        cls._nodes.clear()
