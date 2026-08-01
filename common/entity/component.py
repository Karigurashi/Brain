"""IComponent 接口 —— 所有可挂载模块必须实现的抽象接口。"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .entity import Entity


class IComponent(ABC):
    """组件接口 —— 定义挂载 / 卸载生命周期。

    构造函数: MUST NOT 接收业务参数，仅做字段默认值初始化。
    """

    @abstractmethod
    def OnInitialize(self, entity: Entity) -> None:
        """挂载后初始化回调。

        由 Entity.AddComponent() / GetComponent() 自动调用，传入所属 Entity 实例。
        子类必须实现此方法，通过 entity.GetComponent() 注入依赖。

        Args:
            entity: 当前所属的 Entity 实例。
        """
        ...

    @abstractmethod
    def OnDestroy(self) -> None:
        """从 Entity 卸载时回调。

        子类必须实现此方法执行清理逻辑。
        """
        ...
