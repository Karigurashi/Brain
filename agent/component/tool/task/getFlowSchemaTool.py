"""Get Flow Schema tool —— return available node types and their config schemas."""

from __future__ import annotations

import json

from agent.component.contex.eContextLodLevel import EContextLodLevel

from ..baseTool import BaseTool, EToolParallelMode
from ..eToolCategory import EToolCategory
from ..toolResult import ToolResult
from ..toolComponent import ToolComponent


@ToolComponent.Register
class GetFlowSchemaTool(BaseTool):
    """Return all registered workflow node types with config schemas.

    The AI calls this before generating a workflow JSON to discover
    available node types, their config parameters, and defaults.
    """

    name: str = "getFlowSchema"
    description: str = "Get workflow node types and JSON format"
    category: EToolCategory = EToolCategory.TASK
    parallelMode: EToolParallelMode = EToolParallelMode.SAFE
    resultLodLevel = EContextLodLevel.SUMMARIZABLE
    parameters: dict = {
        "type": "object",
        "properties": {},
        "required": [],
    }

    def _Invoke(self) -> ToolResult:
        """Return registered node types, their config schemas, and JSON format docs.

        Returns:
            ToolResult with JSON containing node info list and format guide.
        """
        from task.workflow import NodeRegistry  # noqa: F811

        nodeInfos = NodeRegistry.GetAllNodeInfo()

        schema = {
            "format": {
                "description": "Workflow JSON: {name, nodes, edges}. Nodes: [{id, type, config?}]. Edges: [{from, to, type?}]",
                "types": {"OUT": 0, "SUB_NODE": 1},
                "rules": [
                    "Must have one Action as entry node",
                    "Default type is OUT(0); Sequence/Parallel children use SUB_NODE(1)",
                ],
                "demo": {
                    "name": "Demo",
                    "nodes": [
                        {"id": 1, "type": "Action/Begin"},
                        {"id": 2, "type": "Composite/Sequence"},
                        {"id": 3, "type": "Action/Agent", "config": {"SystemPrompt": "Research a topic.", "UserMessage": "AI safety"}},
                        {"id": 4, "type": "Action/Agent", "config": {"SystemPrompt": "Write a report based on above."}},
                    ],
                    "edges": [
                        {"from": 1, "to": 2},
                        {"from": 2, "to": 3, "type": 1},
                        {"from": 2, "to": 4, "type": 1},
                    ],
                },
            },
            "nodeTypes": nodeInfos,
        }

        return ToolResult.Ok(
            content=json.dumps(schema, ensure_ascii=False, indent=2),
            data=schema,
            toolName=self.name,
        )
