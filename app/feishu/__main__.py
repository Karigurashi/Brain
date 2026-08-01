"""飞书通道入口 —— ``python -m app.feishu``。

配置来自 ``workspace/settings.json`` 的 ``channel.feishu``。
可选命令行参数覆盖 modelName::

    python -m app.feishu
    python -m app.feishu v4pro
"""

from __future__ import annotations

import sys

from app.channel import LifecycleComponent
from app.feishu.feishuApp import FeishuApp
from app.feishu.feishuConfig import FeishuAppConfig
from setting import Settings


def main() -> None:
    config = Settings.Get("channel.feishu", FeishuAppConfig)
    if len(sys.argv) > 1:
        config.modelName = sys.argv[1]
    if not config.appId or not config.appSecret:
        print(
            "Missing channel.feishu.appId / appSecret in workspace/settings.json.",
            file=sys.stderr,
        )
        sys.exit(1)

    app = FeishuApp(config)
    app.GetComponent(LifecycleComponent).Start()


if __name__ == "__main__":
    main()
