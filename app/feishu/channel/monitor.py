"""飞书 WebSocket 事件监视器（固定长连接，对齐官方 channel/monitor）。

lark_oapi.ws.Client.start() 依赖模块级 loop + run_until_complete，
不能在已有 asyncio.run 的循环内直接调用。因此在独立线程里自建 loop，
事件回调经 run_coroutine_threadsafe 投递回主循环。
"""

from __future__ import annotations

import asyncio
import json
import threading
from typing import Any, Optional

from app.channel import EChannelState, LifecycleComponent
from app.feishu.channel.eventHandlers import HandleCardActionEventAsync, HandleMessageEventAsync
from app.feishu.channel.types import MonitorContext
from common.cancellationToken import CancellationToken
from common.logger import Logger


class FeishuMonitor:
    """飞书 WebSocket 事件接入：注册消息与卡片回调。"""

    def __init__(self, ctx: MonitorContext) -> None:
        self._ctx = ctx
        self._stopEvent = asyncio.Event()
        self._mainLoop: Optional[asyncio.AbstractEventLoop] = None
        self._wsThread: Optional[threading.Thread] = None

    async def StartAsync(self, cancellationToken: Optional[CancellationToken] = None) -> None:
        if cancellationToken is not None:
            cancellationToken.ThrowIfCancellationRequested()
        Logger.Info("feishu monitor starting: websocket")
        await self._RunWebsocketAsync(cancellationToken)

    async def StopAsync(self, cancellationToken: Optional[CancellationToken] = None) -> None:
        if cancellationToken is not None:
            cancellationToken.ThrowIfCancellationRequested()
        self._stopEvent.set()

    async def DispatchEventAsync(
        self,
        eventType: str,
        data: dict[str, Any],
        cancellationToken: Optional[CancellationToken] = None,
    ) -> Any:
        if eventType in ("im.message.receive_v1", "im.message.receive_v1.event"):
            await HandleMessageEventAsync(self._ctx, data, cancellationToken)
            return None
        if eventType in ("card.action.trigger", "card.action.trigger.event"):
            return await HandleCardActionEventAsync(self._ctx, data, cancellationToken)
        Logger.Debug(f"feishu monitor: ignore eventType={eventType}")
        return None

    async def _RunWebsocketAsync(self, cancellationToken: Optional[CancellationToken] = None) -> None:
        try:
            import lark_oapi as lark
            import lark_oapi.ws.client as wsClientMod
            from lark_oapi.event.dispatcher_handler import EventDispatcherHandler
        except ImportError:
            Logger.Error("lark_oapi not installed; cannot start feishu websocket. pip install lark-oapi")
            await self._WaitStopAsync(cancellationToken)
            return

        # 参考 openclaw-lark：注册所有可能收到的事件，暂不处理的用空处理器消费，
        # 避免 SDK 打印 "processor not found" ERROR。
        handler = (
            EventDispatcherHandler.builder("", "")
            .register_p2_im_message_receive_v1(self._OnWsMessage)
            .register_p2_card_action_trigger(self._OnWsCardAction)
            .register_p2_im_message_reaction_created_v1(self._OnWsNoop)
            .register_p2_im_message_reaction_deleted_v1(self._OnWsNoop)
            .build()
        )

        self._mainLoop = asyncio.get_running_loop()
        appId = self._ctx.config.appId
        appSecret = self._ctx.config.appSecret

        def _RunClient() -> None:
            # lark_oapi 在 import 时可能已捕获主循环；线程内必须换新 loop
            newLoop = asyncio.new_event_loop()
            asyncio.set_event_loop(newLoop)
            wsClientMod.loop = newLoop
            # DEBUG：能看到是否有任何 data frame 到达（receive message / handle failed）
            import logging as _logging
            _logging.getLogger("Lark").setLevel(_logging.DEBUG)
            cli = lark.ws.Client(
                appId,
                appSecret,
                event_handler=handler,
                log_level=lark.LogLevel.DEBUG,
            )
            try:
                cli.start()
            except Exception as exc:
                Logger.Error(f"feishu websocket client exited: {exc}")
            finally:
                # 连接退出时唤醒主循环，避免 OnStartAsync 永久挂起
                mainLoop = self._mainLoop
                if mainLoop is not None and not mainLoop.is_closed():
                    try:
                        mainLoop.call_soon_threadsafe(self._stopEvent.set)
                    except RuntimeError:
                        pass

        Logger.Info("feishu websocket client starting (lark DEBUG on)")
        # daemon：RequestStop / Ctrl+C 后主循环可收尾 StopAsync，不被 ws 线程拖死
        self._wsThread = threading.Thread(
            target=_RunClient, name="feishu-ws", daemon=True
        )
        self._wsThread.start()
        await self._WaitStopAsync(cancellationToken)
        Logger.Info("feishu monitor stopping")

    def _ScheduleOnMainLoop(self, coro: Any) -> None:
        mainLoop = self._mainLoop
        if mainLoop is None or mainLoop.is_closed():
            Logger.Warning("feishu monitor: main loop unavailable, drop event")
            return
        future = asyncio.run_coroutine_threadsafe(coro, mainLoop)

        def _OnDone(fut: Any) -> None:
            try:
                fut.result()
            except Exception as exc:
                Logger.Error(f"feishu monitor: event handler failed: {exc}")

        future.add_done_callback(_OnDone)

    def _OnWsMessage(self, data: Any) -> None:
        Logger.Info(
            f"feishu[{self._ctx.accountId}]: ws message event received "
            f"type={type(data).__name__}"
        )
        payload = data if isinstance(data, dict) else _ToDict(data)
        self._ScheduleOnMainLoop(HandleMessageEventAsync(self._ctx, payload))

    def _OnWsNoop(self, data: Any) -> None:
        """空处理器 —— 消费 SDK 已注册但暂不处理的 WebSocket 事件。

        参考 openclaw-lark：register no-op handlers to avoid SDK warnings
        about missing handlers。当前覆盖 reaction.created/deleted。
        """

    def _OnWsCardAction(self, data: Any) -> Any:
        Logger.Info(
            f"feishu[{self._ctx.accountId}]: ws card action received "
            f"type={type(data).__name__}"
        )
        payload = data if isinstance(data, dict) else _ToDict(data)
        self._ScheduleOnMainLoop(HandleCardActionEventAsync(self._ctx, payload))
        return {"toast": {"type": "info", "content": "处理中..."}}

    async def _WaitStopAsync(self, cancellationToken: Optional[CancellationToken] = None) -> None:
        """等待停止：_stopEvent / Lifecycle 离开 RUNNING / cancellationToken。"""
        lifecycle = self._ctx.app.GetComponent(LifecycleComponent)
        while not self._stopEvent.is_set():
            if lifecycle.State != EChannelState.RUNNING:
                break
            if cancellationToken is not None and cancellationToken.IsCancellationRequested:
                break
            try:
                await asyncio.wait_for(self._stopEvent.wait(), timeout=0.25)
            except asyncio.TimeoutError:
                continue


def _ToDict(data: Any) -> dict[str, Any]:
    if hasattr(data, "__dict__"):
        try:
            return json.loads(json.dumps(data, default=lambda o: getattr(o, "__dict__", str(o))))
        except Exception:
            pass
    if isinstance(data, dict):
        return data
    return {"raw": str(data)}
