"""飞书 Channel —— 官方卡片能力 Python 移植 + mango channel / AgentSdk。

目录对齐 openclaw-lark::

    card/        出站卡片（CardKit 流式、reply dispatcher）
    channel/     事件监视与 card.action 回调（无话题）
    core/        LarkClient / footer / targets
    messaging/   outbound 发送与 interactive 入站转换
    component/   mango 组件（Platform / Card）

Usage::

    from app.feishu import FeishuApp, FeishuAppConfig
    from app.channel import LifecycleComponent

    app = FeishuApp()  # 从 settings.json channel.feishu 解析
    app.GetComponent(LifecycleComponent).Start()
"""


from app.feishu.card import CreateFeishuReplyDispatcher, StreamingCardController
from app.feishu.component import CardComponent, FeishuPlatformComponent
from app.feishu.feishuApp import FeishuApp
from app.feishu.feishuConfig import FeishuAppConfig

__all__ = [
    "CardComponent",
    "CreateFeishuReplyDispatcher",
    "FeishuApp",
    "FeishuAppConfig",
    "FeishuPlatformComponent",
    "StreamingCardController",
]
