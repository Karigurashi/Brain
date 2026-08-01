"""SyncEventBus —— 泛型同步事件总线基类。

提供 Subscribe / Unsubscribe / Push / Clear 核心机制，
子类通过覆写 _OnPostPush 实现后处理钩子。
"""

from __future__ import annotations

from typing import Callable, Generic, TypeVar

from common.logger import Logger

TEvent = TypeVar("TEvent")


class SyncEventBus(Generic[TEvent]):
    """泛型同步事件总线。

    监听器异常被隔离，不会中断事件分发链。
    所有操作均为同步，无需 asyncio 桥接。

    子类覆写 _OnPostPush(event) 可实现推送后处理（如对象池归还）。
    """

    def __init__(self) -> None:
        self._listeners: list[Callable[[TEvent], None]] = []

    def AddListener(self, callback: Callable[[TEvent], None]) -> None:
        """注册事件监听器。"""
        self._listeners.append(callback)

    def RemoveListener(self, callback: Callable[[TEvent], None]) -> None:
        """移除事件监听器，若不存在则静默忽略。"""
        try:
            self._listeners.remove(callback)
        except ValueError:
            pass

    def Push(self, event: TEvent) -> None:
        """同步推送事件给所有监听器。

        遍历所有已注册回调并逐一调用，单个监听器异常不会中断后续分发。
        """
        for listener in self._listeners:
            try:
                listener(event)
            except Exception as exc:
                Logger.Error(f"{type(self).__name__}: listener failed: {exc}")
        self._OnPostPush(event)

    def _OnPostPush(self, event: TEvent) -> None:
        """推送后处理钩子，默认无操作。子类可覆写。"""
        pass

    def RemoveAllListeners(self) -> None:
        """清空所有监听器，避免泄漏。"""
        self._listeners.clear()
