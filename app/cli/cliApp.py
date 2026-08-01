"""CliApp —— CLI REPL 终端入口，继承 BaseChannel 的纯装配壳。

不含任何细节逻辑：全部 CLI 平台行为（REPL 主循环、渲染、中断处理）
由 CliPlatformComponent 承载；生命周期与消息路由由 BaseChannel 内置
组件（LifecycleComponent / RouterComponent）承担。

config 为 None 时从 ``settings.json`` 的 ``channel.cli`` 解析 CliConfig，
解析失败则回退默认值。

Usage::

    app = CliApp()  # Settings.Get("channel.cli", CliConfig)
    app.GetComponent(LifecycleComponent).Start()  # 同步入口，内部 asyncio.run()
"""

from __future__ import annotations

import logging
from typing import Optional

from common.logger import Logger
from setting import Settings

from ..channel import BaseChannel
from .cliConfig import CliConfig
from .component.console import ConsoleComponent
from .component.input import InputComponent
from .component.platform import CliPlatformComponent
from .component.render import RenderComponent
from .component.repl import ReplComponent


class CliApp(BaseChannel):
    """CLI 终端 Channel —— 装配 CliPlatformComponent 的纯外壳。

    Usage::

        app = CliApp()
        app.GetComponent(LifecycleComponent).Start()
    """

    def __init__(
        self,
        config: Optional[CliConfig] = None,
    ) -> None:
        super().__init__(config or Settings.Get("channel.cli", CliConfig))

        Logger.RedirectToStdout()
        Logger.SetLevel(logging.WARNING)

    def SetupComponents(self) -> None:
        super().SetupComponents()
        self._platformComponent = self.AddComponent(CliPlatformComponent)

        # CLI 领域组件
        self.AddComponent(ConsoleComponent)
        self.AddComponent(RenderComponent)
        self.AddComponent(InputComponent)
        self.AddComponent(ReplComponent)

        self.GetComponent(RenderComponent).PrintBanner()