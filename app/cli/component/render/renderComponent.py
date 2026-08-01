"""RenderComponent —— CLI 渲染组件，持有 CliRenderer 并承接终端打印职责。

封装事件渲染入口（OnAgentEvent）与固定版面打印
（Banner / Goodbye / UsageFooter / Cancelling 提示），
用量数据经 GroupComponent 查询。
"""

from __future__ import annotations

import sys
from typing import TYPE_CHECKING, Optional

from agent import EAgentStreamEventType
from app.channel import BaseChannelComponent

from .cliRenderer import CliRenderer

if TYPE_CHECKING:
    from agent import AgentStreamEvent


class RenderComponent(BaseChannelComponent):
    """CLI 渲染组件 —— 事件渲染调度 + 固定版面打印。

    由 CliPlatformComponent.OnInitialize 编排触发，通过
    channel.GetComponent(RenderComponent) 访问。
    """

    CLI_GROUP_ID: str = "cli"

    def __init__(self) -> None:
        super().__init__()
        self._renderer: Optional[CliRenderer] = None

    @property
    def CliConfig(self):
        return self._channel.Config  # type: ignore[union-attr,return-value]

    def OnInitialize(self, entity) -> None:
        super().OnInitialize(entity)
        cliConfig = self._channel.Config  # type: ignore[union-attr]
        self._renderer = CliRenderer(cliConfig)

    @property
    def Renderer(self) -> CliRenderer:
        return self._renderer  # type: ignore[return-value]

    # ---- Agent 事件渲染 ----

    def OnAgentEvent(self, event: AgentStreamEvent) -> None:
        self._renderer.OnEvent(event)  # type: ignore[union-attr]
        if event.eventType == EAgentStreamEventType.DONE:
            self.PrintUsageFooter()

    # ---- 固定版面 ----

    def PrintBanner(self) -> None:
        from app.channel import GroupComponent
        from ..repl import ReplComponent

        channel = self._channel  # type: ignore[assignment]
        groupComponent = channel.GetComponent(GroupComponent)
        repl = channel.GetComponent(ReplComponent)
        groupName = repl.CliGroup.groupName

        self._renderer.PrintBanner(  # type: ignore[union-attr]
            groupComponent.GetModelName(self.CLI_GROUP_ID) or "unknown",
            groupName,
        )

    def PrintGoodbye(self) -> None:
        c = self.CliConfig
        sys.stdout.write(c.Dim(f"\n  {c.BOX_BL}{c.BOX_H * 20} See you {c.BOX_BR}\n\n"))
        sys.stdout.flush()

    def PrintUsageFooter(self) -> None:
        cliConfig = self.CliConfig
        if not cliConfig.showTokenUsage:
            return

        from app.channel import GroupComponent

        channel = self._channel  # type: ignore[assignment]
        groupComponent = channel.GetComponent(GroupComponent)
        modelName = groupComponent.GetModelName(self.CLI_GROUP_ID) or "unknown"
        promptTokens, completionTokens, cacheHitRate = groupComponent.GetLastTokenUsage(
            self.CLI_GROUP_ID
        )
        if promptTokens == 0 and completionTokens == 0:
            return
        self._renderer.PrintFooter(  # type: ignore[union-attr]
            modelName, promptTokens, completionTokens, cacheHitRate
        )

    def PrintCancelling(self) -> None:
        c = self.CliConfig
        sys.stdout.write(f"\n{c.Color('[Cancelling...]', c.AMBER)}\n")
        sys.stdout.flush()