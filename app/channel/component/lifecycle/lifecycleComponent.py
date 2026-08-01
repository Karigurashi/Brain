"""LifecycleComponent —— Channel 生命周期组件，管理运行状态机与启停编排。

持有 EChannelState 状态机，驱动 Start / Stop 全流程；
平台特定的启动 / 停止逻辑委托给 channel.Platform（BasePlatformComponent）。
"""

from __future__ import annotations

import asyncio
import signal
import traceback
from typing import Optional

from common.cancellationToken import CancellationToken
from common.logger import Logger

from ...channelComponent import BaseChannelComponent
from ...eChannelState import EChannelState


class LifecycleComponent(BaseChannelComponent):
    """Channel 生命周期组件 —— 状态机 + 启停编排。

    由 BaseChannel.__init__ 挂载，通过 channel.GetComponent(LifecycleComponent) 访问。

    状态流转::

        STOPPED → STARTING → RUNNING → STOPPING → STOPPED
                            ↘ ERROR（启动异常）

    用法::

        lifecycle = channel.GetComponent(LifecycleComponent)
        lifecycle.Start()              # 同步入口，内部 asyncio.run()
        await lifecycle.StartAsync()   # 异步入口
        lifecycle.RequestStop()        # 请求停止（/exit、EOF、Ctrl+C 空闲时）
    """

    def __init__(self) -> None:
        super().__init__()
        self._state: EChannelState = EChannelState.STOPPED

    # ---- 状态 ----

    @property
    def State(self) -> EChannelState:
        """Channel 当前运行状态。"""
        return self._state

    def RequestStop(self) -> None:
        """请求停止 Channel（置 STOPPING）。

        平台主循环应检测后退出 OnStartAsync；``Start()`` 的 finally
        会统一执行 StopAsync（群组销毁 + 会话落盘）。
        """
        self._state = EChannelState.STOPPING

    # ---- 启动 ----

    def Start(self) -> None:
        """同步入口，启动 Channel 并阻塞直到退出。

        注册 SIGTERM / SIGBREAK 处理器，使 taskkill（不带 /F）和
        关控制台窗口也能触发正常的 StopAsync 清理链路。
        SIGKILL（taskkill /F、任务管理器强制结束）无法拦截。

        无论正常返回、Ctrl+C 还是平台主循环因 RequestStop 退出，
        最终都会执行 StopAsync（DestroyAllGroups → 会话落盘）。
        """
        def _OnTerminate(signum: int, frame: object) -> None:
            self.RequestStop()

        for sig in (signal.SIGTERM, signal.SIGBREAK):
            try:
                signal.signal(sig, _OnTerminate)
            except (ValueError, AttributeError):
                pass  # 非主线程或平台不支持时忽略

        try:
            asyncio.run(self.StartAsync())
        except KeyboardInterrupt:
            self.RequestStop()
        finally:
            if self._state != EChannelState.STOPPED:
                try:
                    asyncio.run(self.StopAsync())
                except Exception as exc:
                    Logger.Error(f"LifecycleComponent.Start: StopAsync failed: {exc}")

    async def StartAsync(
        self,
        cancellationToken: Optional[CancellationToken] = None,
    ) -> None:
        """启动 Channel，触发平台启动钩子。

        Args:
            cancellationToken: 取消令牌。
        """
        if self._state != EChannelState.STOPPED:
            Logger.Warning(
                f"LifecycleComponent.StartAsync: already in state {self._state.name}"
            )
            return

        channel = self._channel  # type: ignore[assignment]
        self._state = EChannelState.STARTING
        try:
            self._state = EChannelState.RUNNING
            await channel.Platform.OnStartAsync(cancellationToken)
            Logger.Info(f"BaseChannel started: {type(channel).__name__}")
        except Exception as exc:
            self._state = EChannelState.ERROR
            Logger.Error(f"LifecycleComponent.StartAsync failed: {exc}")
            raise

    # ---- 停止 ----

    async def StopAsync(
        self,
        cancellationToken: Optional[CancellationToken] = None,
    ) -> None:
        """停止 Channel，销毁全部组件并触发平台停止钩子。

        先缓存平台组件引用，再销毁 Entity 全部组件（群组随之销毁），
        最后调用平台 OnStopAsync 钩子释放平台资源。

        Args:
            cancellationToken: 取消令牌。
        """
        if self._state == EChannelState.STOPPED:
            return

        channel = self._channel  # type: ignore[assignment]
        self._state = EChannelState.STOPPING

        platform = channel.Platform

        # 1. 异步销毁所有群组（等待消费者协程退出）
        from ..group import GroupComponent
        groupComp = channel.GetComponent(GroupComponent)
        try:
            await groupComp.DestroyAllGroupsAsync()
        except Exception as exc:
            Logger.Error(
                f"LifecycleComponent.StopAsync: DestroyAllGroupsAsync failed: {exc}\n"
                f"{traceback.format_exc()}"
            )
            raise

        # 2. 销毁剩余组件
        try:
            channel.Destroy()
        except Exception as exc:
            Logger.Error(
                f"LifecycleComponent.StopAsync: channel.Destroy failed: {exc}\n"
                f"{traceback.format_exc()}"
            )
            raise

        try:
            await platform.OnStopAsync(cancellationToken)
        except Exception as exc:
            Logger.Error(f"LifecycleComponent.StopAsync: OnStopAsync failed: {exc}")

        self._state = EChannelState.STOPPED
        Logger.Info(f"BaseChannel stopped: {type(channel).__name__}")
