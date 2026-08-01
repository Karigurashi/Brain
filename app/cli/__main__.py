"""Agent CLI 终端入口点 —— 支持 ``python -m app.cli`` 启动。

配置来自 ``workspace/settings.json`` 的 ``channel.cli``；
解析失败时使用 CliConfig 默认值。可选命令行参数覆盖 modelName::

    python -m app.cli
    python -m app.cli v4pro
"""

from __future__ import annotations

import sys

from setting import Settings

from ..channel import LifecycleComponent
from .cliApp import CliApp
from .cliConfig import CliConfig


def main() -> None:
    """CLI 入口函数，解析命令行参数并启动 REPL。"""
    config = Settings.Get("channel.cli", CliConfig)
    if len(sys.argv) > 1:
        config.modelName = sys.argv[1]

    app = CliApp(config)
    app.GetComponent(LifecycleComponent).Start()


if __name__ == "__main__":
    main()
