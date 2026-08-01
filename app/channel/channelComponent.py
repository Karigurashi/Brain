"""BaseChannelComponent —— Channel 层组件基类，实现 IComponent 接口提供可选钩子。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

from common.entity.component import IComponent

if TYPE_CHECKING:
    from .baseChannel import BaseChannel


class BaseChannelComponent(IComponent):
    """Channel 层组件基类 —— OnInitialize 统一捕获所属 BaseChannel，子类按需覆盖。

    子类 override OnInitialize 时必须调用 super().OnInitialize(channel)，
    确保 _channel 引用被正确注入。
    """

    def __init__(self) -> None:
        self._channel: Optional[BaseChannel] = None

    def OnInitialize(self, entity) -> None:
        """挂载后捕获所属 BaseChannel 引用。"""
        self._channel = entity

    def OnDestroy(self) -> None:
        pass
