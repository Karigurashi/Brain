"""agent/contex —— 上下文管理模块。

基于 LOD 四级分级系统的上下文管理：
- ContextComponent: 四阶段编排（Ingest/Assemble/Compact/AfterTurn）
- ContextCompactor: LLM 驱动的批量上下文摘要压缩

注意：ContextComponent 和 ContextCompactor 不在模块级导出，
以避免与 eventBus 的循环导入。请直接从子模块导入：
  from agent.component.contex.contextComponent import ContextComponent
"""

from .contextMessage import ContextMessage
from .eContextLodLevel import EContextLodLevel

__all__ = [
    "ContextMessage",
    "EContextLodLevel",
]
