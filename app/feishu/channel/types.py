"""飞书 channel 监视器上下文类型（对齐官方 channel/types）。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from app.feishu.core.larkClient import LarkClient
    from app.feishu.feishuApp import FeishuApp
    from app.feishu.feishuConfig import FeishuAppConfig


@dataclass
class MonitorContext:
    """Monitor 事件处理上下文。"""

    app: "FeishuApp"
    config: "FeishuAppConfig"
    client: "LarkClient"
    accountId: str = "default"
    botOpenId: Optional[str] = None
