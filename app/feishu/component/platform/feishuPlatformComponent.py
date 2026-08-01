"""FeishuPlatformComponent —— 飞书平台 SPI，对接 AgentSdk 与卡片组件。"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Optional

from app.channel import BasePlatformComponent
from app.feishu.channel import FeishuMonitor, MonitorContext
from app.feishu.component.card import CardComponent
from common.cancellationToken import CancellationToken
from common.logger import Logger

if TYPE_CHECKING:
    from agent import AgentStreamEvent


class FeishuPlatformComponent(BasePlatformComponent):
    """飞书平台组件 —— 启动 Monitor，事件经 CardComponent 渲染。

    指令上下文沿用基类 CommandContext（缓冲 + OnSendResponseAsync）。
    """

    def __init__(self) -> None:
        super().__init__()
        self._monitor: Optional[FeishuMonitor] = None

    async def OnStartAsync(
        self,
        cancellationToken: Optional[CancellationToken] = None,
    ) -> None:
        channel = self._channel  # type: ignore[assignment]
        config = channel.Config
        if not config.appId or not config.appSecret:
            raise ValueError("FeishuAppConfig.appId / appSecret is required")

        card = channel.GetComponent(CardComponent)
        # 绑定 asyncio.run 主循环，供 Agent EventBus 后台推送安全调度
        card.BindEventLoop(asyncio.get_running_loop())
        client = card.Client
        botOpenId: Optional[str] = None
        try:
            probe = await client.ProbeAsync(cancellationToken)
            if probe.ok:
                botOpenId = probe.botOpenId
                Logger.Info(
                    f"feishu bot ready: name={probe.botName}, openId={botOpenId}"
                )
            else:
                Logger.Warning(f"feishu probe failed: {probe.error}")
        except Exception as exc:
            Logger.Warning(f"feishu probe skipped: {exc}")

        ctx = MonitorContext(
            app=channel,
            config=config,
            client=client,
            accountId="default",
            botOpenId=botOpenId,
        )
        self._monitor = FeishuMonitor(ctx)
        await self._monitor.StartAsync(cancellationToken)

    async def OnStopAsync(
        self,
        cancellationToken: Optional[CancellationToken] = None,
    ) -> None:
        if self._monitor is not None:
            await self._monitor.StopAsync(cancellationToken)
            self._monitor = None
        channel = self._channel  # type: ignore[assignment]
        # CloseAsync 内会 DrainShutdownHooks + abort 残余流式卡
        await channel.GetComponent(CardComponent).CloseAsync()

    def OnAgentEventSync(self, groupId: str, event: "AgentStreamEvent") -> None:
        channel = self._channel  # type: ignore[assignment]
        channel.GetComponent(CardComponent).OnAgentEventSync(groupId, event)

    async def OnSendResponseAsync(
        self,
        groupId: str,
        content: str,
        cancellationToken: Optional[CancellationToken] = None,
    ) -> None:
        channel = self._channel  # type: ignore[assignment]
        await channel.GetComponent(CardComponent).SendTextResponseAsync(groupId, content)

