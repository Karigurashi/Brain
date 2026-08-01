"""入站媒体解析（对齐官方 messaging/inbound）。"""

from app.feishu.messaging.inbound.mediaResolver import (
    DownloadResourcesAsync,
    FeishuMediaInfo,
    ResourceDescriptor,
    SubstituteMediaPaths,
)

__all__ = [
    "DownloadResourcesAsync",
    "FeishuMediaInfo",
    "ResourceDescriptor",
    "SubstituteMediaPaths",
]
