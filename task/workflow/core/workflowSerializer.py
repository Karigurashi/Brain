"""WorkflowSerializer —— Workflow 序列化/反序列化，独立于 Workflow 数据类。"""

from __future__ import annotations

import json
from typing import Any, TYPE_CHECKING

from .nodeRegistry import NodeRegistry
from .workflowEdge import WorkflowEdge, EEdgeType

if TYPE_CHECKING:
    from ..workflow import Workflow


class WorkflowSerializer:
    """Workflow 与 dict/JSON 之间转换的静态工具类。

    遵循项目序列化规范：数据类自身不持有序列化方法，
    自定义字段映射逻辑由专用的 Serializer 处理。
    """

    @staticmethod
    def FromDict(data: dict) -> "Workflow":
        """从字典反序列化 Workflow。

        Args:
            data: 包含 name、nodes、edges 的字典。

        Example::

            wf = WorkflowSerializer.FromDict({
                "name": "Test",
                "nodes": [{"id": 1, "type": "Action/Begin", "x": 0, "y": 0}],
                "edges": [{"from": 1, "to": 2}],
            })
        """
        from ..workflow import Workflow

        wf = Workflow(name=data.get("name", ""))
        for nodeData in data.get("nodes", []):
            nodeClass = NodeRegistry.Get(nodeData["type"])
            if nodeClass is None:
                raise ValueError(f"Unknown node type '{nodeData['type']}'")
            config = dict(nodeData.get("config") or {})
            if "name" in nodeData and nodeData["name"] is not None:
                config["name"] = nodeData["name"]
            instance = nodeClass(**config)
            wf.graph.AddNode(
                nodeId=int(nodeData["id"]),
                executor=instance,
                x=float(nodeData.get("x", 0)),
                y=float(nodeData.get("y", 0)),
            )
        for edgeData in data.get("edges", []):
            wf.graph.AddEdgeObj(WorkflowEdge(
                fromNodeId=int(edgeData["from"]),
                toNodeId=int(edgeData["to"]),
                edgeType=int(edgeData.get("type", 0)),
            ))
        return wf

    @staticmethod
    def FromJson(jsonStr: str) -> "Workflow":
        """从 JSON 字符串反序列化 Workflow。

        Args:
            jsonStr: JSON 字符串。

        Returns:
            重建的 Workflow 实例。
        """
        return WorkflowSerializer.FromDict(json.loads(jsonStr))

    @staticmethod
    def ToDict(wf: "Workflow") -> dict[str, Any]:
        """将 Workflow 导出为字典。

        Args:
            wf: Workflow 实例。

        Returns:
            包含 name、nodes、edges 的字典。
        """
        result: dict[str, Any] = {"name": wf.name}
        nodesData: list[dict] = []
        for nid in wf.graph.GetAllNodeIds():
            node = wf.graph.GetNode(nid)
            if node is None:
                continue
            x, y = node.x, node.y
            nodeDict: dict = {"id": nid, "type": node.nodeType, "x": x, "y": y}
            if node.name is not None:
                nodeDict["name"] = node.name
            config = {
                k: v for k, v in vars(node).items()
                if not k.startswith("_") and k not in (
                    "nodeType", "category", "displayName", "description", "name", "x", "y"
                )
            } or None
            if config:
                nodeDict["config"] = config
            nodesData.append(nodeDict)
        result["nodes"] = nodesData
        edges = []
        for e in wf.graph.GetAllEdges():
            d: dict[str, Any] = {"from": e.fromNodeId, "to": e.toNodeId}
            if e.edgeType != EEdgeType.OUT:
                d["type"] = e.edgeType
            edges.append(d)
        result["edges"] = edges
        return result

    @staticmethod
    def ToJson(wf: "Workflow", indent: int = 2) -> str:
        """将 Workflow 导出为格式化的 JSON 字符串。

        Args:
            wf: Workflow 实例。
            indent: 缩进空格数。

        Returns:
            JSON 字符串。
        """
        return json.dumps(WorkflowSerializer.ToDict(wf), indent=indent, ensure_ascii=False)
