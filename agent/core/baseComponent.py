"""BaseComponent —— Agent 层组件基类，实现 IComponent 接口提供可选钩子。"""

from __future__ import annotations

from common.entity.component import IComponent


class BaseComponent(IComponent):
    """Agent 层组件基类 —— 提供 OnInitialize / OnDestroy 空实现，子类按需覆盖。"""

    def OnInitialize(self, entity) -> None:
        pass

    def OnDestroy(self) -> None:
        pass
