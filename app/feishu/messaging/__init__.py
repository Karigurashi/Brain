"""飞书消息模块。"""

from app.feishu.messaging.inbound import (
    DownloadResourcesAsync,
    FeishuMediaInfo,
    ResourceDescriptor,
    SubstituteMediaPaths,
)
from app.feishu.messaging.types import FeishuSendResult

__all__ = [
    "DownloadResourcesAsync",
    "FeishuMediaInfo",
    "FeishuSendResult",
    "ResourceDescriptor",
    "SubstituteMediaPaths",
]
