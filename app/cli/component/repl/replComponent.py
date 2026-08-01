"""ReplComponent —— CLI REPL 组件，主循环编排与中断分流。

承接原 CliApp 的 REPL 职责：读取输入（InputComponent）→ 指令分发或
Agent 阻塞执行（RouterComponent）。取消令牌由 AgentSdk 内部管理。
"""

from __future__ import annotations

import signal
import traceback
from typing import Optional

from common.cancellationToken import CancellationToken

from app.channel import (
    BaseChannelComponent,
    ChannelMessage,
    EChannelState,
    GroupComponent,
    GroupContext,
    LifecycleComponent,
    RouterComponent,
)

from ..input import InputComponent
from ..render import RenderComponent


class ReplComponent(BaseChannelComponent):
    """CLI REPL 组件 —— 主循环 + SIGINT 分流。

    由 CliPlatformComponent.OnInitialize 编排触发，通过
    channel.GetComponent(ReplComponent) 访问。
    """

    CLI_GROUP_ID: str = "cli"

    def __init__(self) -> None:
        super().__init__()
        self._cliGroup: Optional[GroupContext] = None

    # ---- 初始化 ----

    def OnInitialize(self, entity) -> None:
        super().OnInitialize(entity)
        channel = self._channel  # type: ignore[assignment]
        self._cliGroup = channel.GetComponent(GroupComponent).EnsureGroup(
            self.CLI_GROUP_ID, "CLI"
        )
        signal.signal(signal.SIGINT, self.HandleInterrupt)

    @property
    def CliGroup(self) -> GroupContext:
        return self._cliGroup  # type: ignore[return-value]

    # ---- REPL 主循环 ----

    async def RunAsync(
        self,
        cancellationToken: Optional[CancellationToken] = None,
    ) -> None:
        channel = self._channel  # type: ignore[assignment]
        lifecycleComponent = channel.GetComponent(LifecycleComponent)
        inputComponent = channel.GetComponent(InputComponent)
        renderComponent = channel.GetComponent(RenderComponent)

        try:
            while lifecycleComponent.State == EChannelState.RUNNING:
                userInput = await inputComponent.ReadInputAsync()
                if userInput is None:
                    lifecycleComponent.RequestStop()
                    break
                userInput = userInput.rstrip('\n\r')
                if not userInput:
                    continue
                await self._ProcessInputAsync(userInput)
        finally:
            await lifecycleComponent.StopAsync()
            renderComponent.PrintGoodbye()

    # ---- 输入处理 ----

    async def _ProcessInputAsync(self, userInput: str) -> None:
        channel = self._channel  # type: ignore[assignment]
        msg = ChannelMessage(
            groupId=self.CLI_GROUP_ID,
            userId="user",
            content=userInput,
        )

        try:
            await channel.GetComponent(RouterComponent).SendMessageAsync(msg)
        except Exception:
            traceback.print_exc()

    # ---- 信号处理 ----

    def HandleInterrupt(self, signum: int, frame: object) -> None:
        channel = self._channel  # type: ignore[assignment]
        if channel.Sdk.IsRunning(self.CLI_GROUP_ID):
            channel.Sdk.Cancel(self.CLI_GROUP_ID)
            channel.GetComponent(RenderComponent).PrintCancelling()
        else:
            channel.GetComponent(LifecycleComponent).RequestStop()