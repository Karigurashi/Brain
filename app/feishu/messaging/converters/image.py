"""image 消息转换（对齐官方 messaging/converters/image.ts）。"""

from __future__ import annotations

import json
from typing import Any

from app.feishu.messaging.inbound.mediaResolver import ResourceDescriptor


def ConvertImageMessage(raw: Any) -> tuple[str, list[ResourceDescriptor]]:
    """解析 image 消息 content → (markdown 占位文本, resources)。"""
    parsed = _SafeParse(raw)
    imageKey = str(parsed.get("image_key") or "").strip()
    if not imageKey:
        return "[image]", []
    return f"![image]({imageKey})", [ResourceDescriptor(type="image", fileKey=imageKey)]


def ExtractPostImageResources(content: dict[str, Any]) -> list[ResourceDescriptor]:
    """从 post 富文本中提取 img 元素的 image_key。"""
    resources: list[ResourceDescriptor] = []
    seen: set[str] = set()
    for locale in ("zh_cn", "en_us", "ja_jp"):
        body = content.get(locale)
        if not isinstance(body, dict):
            continue
        for row in body.get("content") or []:
            if not isinstance(row, list):
                continue
            for item in row:
                if not isinstance(item, dict):
                    continue
                if item.get("tag") not in ("img", "image"):
                    continue
                imageKey = str(item.get("image_key") or "").strip()
                if imageKey and imageKey not in seen:
                    seen.add(imageKey)
                    resources.append(ResourceDescriptor(type="image", fileKey=imageKey))
        if resources:
            break
    return resources


def _SafeParse(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    try:
        data = json.loads(str(raw or "{}"))
        return data if isinstance(data, dict) else {}
    except json.JSONDecodeError:
        return {}
