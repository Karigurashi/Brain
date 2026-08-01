"""节流 flush 控制器（对齐官方 flush-controller，修复 timer 竞态）。"""

from __future__ import annotations

import asyncio
import time
from typing import Awaitable, Callable, Optional

from app.feishu.card.replyDispatcherTypes import THROTTLE_CONSTANTS


class FlushController:
    def __init__(self, doFlush: Callable[[], Awaitable[None]]) -> None:
        self._doFlush = doFlush
        self._flushInProgress = False
        self._flushResolvers: list[asyncio.Future[None]] = []
        self._needsReflush = False
        self._pendingFlushTimer: Optional[asyncio.Task[None]] = None
        self._lastUpdateTime = 0.0
        self._isCompleted = False
        self._cardMessageReady = False

    def Complete(self) -> None:
        self._isCompleted = True

    def CancelPendingFlush(self) -> None:
        timer = self._pendingFlushTimer
        self._pendingFlushTimer = None
        if timer is not None and not timer.done():
            timer.cancel()

    async def WaitForFlushAsync(self) -> None:
        if not self._flushInProgress:
            return
        loop = asyncio.get_running_loop()
        future: asyncio.Future[None] = loop.create_future()
        self._flushResolvers.append(future)
        await future

    async def FlushAsync(self) -> None:
        if not self._cardMessageReady or self._flushInProgress or self._isCompleted:
            if self._flushInProgress and not self._isCompleted:
                self._needsReflush = True
            return
        self._flushInProgress = True
        self._needsReflush = False
        # 先更新时间戳，防止并发调用同时进入（对齐官方）
        self._lastUpdateTime = time.time() * 1000
        try:
            await self._doFlush()
            self._lastUpdateTime = time.time() * 1000
        finally:
            self._flushInProgress = False
            resolvers = self._flushResolvers
            self._flushResolvers = []
            for resolver in resolvers:
                if not resolver.done():
                    resolver.set_result(None)
            # 飞行中到达的事件：立即跟一帧（timer 先清空再 flush，避免阻断 needsReflush）
            if self._needsReflush and not self._isCompleted and self._pendingFlushTimer is None:
                self._needsReflush = False
                self._pendingFlushTimer = asyncio.create_task(self._RunScheduledFlushAsync(0))

    async def ThrottledUpdateAsync(self, throttleMs: int) -> None:
        if not self._cardMessageReady:
            return
        now = time.time() * 1000
        elapsed = now - self._lastUpdateTime
        if elapsed >= throttleMs:
            self.CancelPendingFlush()
            if elapsed > THROTTLE_CONSTANTS["LONG_GAP_THRESHOLD_MS"]:
                # 长空档后短暂聚合，避免首帧只有 1～2 个字符
                self._lastUpdateTime = now
                self._pendingFlushTimer = asyncio.create_task(
                    self._RunScheduledFlushAsync(THROTTLE_CONSTANTS["BATCH_AFTER_GAP_MS"] / 1000)
                )
            else:
                await self.FlushAsync()
        elif self._pendingFlushTimer is None:
            delaySec = (throttleMs - elapsed) / 1000
            self._pendingFlushTimer = asyncio.create_task(self._RunScheduledFlushAsync(delaySec))

    def CardMessageReady(self) -> bool:
        return self._cardMessageReady

    def SetCardMessageReady(self, ready: bool) -> None:
        self._cardMessageReady = ready
        if ready:
            self._lastUpdateTime = time.time() * 1000

    async def _RunScheduledFlushAsync(self, delaySec: float) -> None:
        """官方顺序：回调入口先清空 timer，再 flush，避免 finally 抹掉新 timer。"""
        me = asyncio.current_task()
        try:
            if delaySec > 0:
                await asyncio.sleep(delaySec)
        except asyncio.CancelledError:
            if self._pendingFlushTimer is me:
                self._pendingFlushTimer = None
            raise
        if self._pendingFlushTimer is me:
            self._pendingFlushTimer = None
        await self.FlushAsync()
