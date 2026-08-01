"""入站媒体下载与路径替换（对齐官方 messaging/inbound/media-resolver.ts）。"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Optional

from app.feishu.core.larkClient import LarkClient
from common.cancellationToken import CancellationToken
from common.const import ERoad
from common.logger import Logger

ResourceType = Literal["image", "file", "audio", "video", "sticker"]

_MIME_TO_EXT: dict[str, str] = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/gif": ".gif",
    "image/webp": ".webp",
    "image/bmp": ".bmp",
    "image/tiff": ".tiff",
}

_MEDIA_DIR = Path(ERoad.WORKSPACE) / ERoad.STORE_DIR / "feishu-media"
_MAX_BYTES_DEFAULT = 30 * 1024 * 1024


@dataclass(slots=True)
class ResourceDescriptor:
    """转换阶段提取的媒体描述（无二进制）。"""

    type: ResourceType
    fileKey: str
    fileName: Optional[str] = None


@dataclass(slots=True)
class FeishuMediaInfo:
    """下载完成后的本地媒体信息。"""

    path: str
    contentType: str
    fileKey: str
    resourceType: ResourceType
    placeholder: str = "<media:image>"


async def DownloadResourcesAsync(
    client: LarkClient,
    messageId: str,
    resources: list[ResourceDescriptor],
    maxBytes: int = _MAX_BYTES_DEFAULT,
    cancellationToken: Optional[CancellationToken] = None,
) -> list[FeishuMediaInfo]:
    """按 ResourceDescriptor 下载消息资源并落盘。"""
    if not messageId or not resources:
        return []

    out: list[FeishuMediaInfo] = []
    _MEDIA_DIR.mkdir(parents=True, exist_ok=True)

    for res in resources:
        try:
            apiType = "image" if res.type == "image" else "file"
            buffer, contentType, fileName = await client.DownloadMessageResourceAsync(
                messageId,
                res.fileKey,
                apiType,
                cancellationToken,
            )
            if len(buffer) > maxBytes:
                Logger.Warning(
                    f"feishu media skipped: {res.fileKey} size={len(buffer)} > max={maxBytes}"
                )
                continue

            mime = (contentType or "").split(";")[0].strip().lower()
            ext = _MIME_TO_EXT.get(mime)
            if not ext and res.fileName:
                ext = Path(res.fileName).suffix
            if not ext:
                ext = ".bin"

            savedName = fileName or res.fileName or f"{uuid.uuid4().hex}{ext}"
            # 避免路径穿越
            savedName = Path(savedName).name
            if not Path(savedName).suffix:
                savedName = f"{savedName}{ext}"
            savedPath = _MEDIA_DIR / f"{uuid.uuid4().hex[:8]}_{savedName}"
            savedPath.write_bytes(buffer)

            out.append(
                FeishuMediaInfo(
                    path=str(savedPath.resolve()),
                    contentType=mime or contentType,
                    fileKey=res.fileKey,
                    resourceType=res.type,
                    placeholder=_InferPlaceholder(res.type),
                )
            )
            Logger.Info(
                f"feishu: downloaded {res.type} resource {res.fileKey} -> {savedPath}"
            )
        except Exception as err:
            Logger.Warning(
                f"feishu: failed to download {res.type} resource {res.fileKey}: {err}"
            )
    return out


def SubstituteMediaPaths(content: str, mediaList: list[FeishuMediaInfo]) -> str:
    """将正文中的 image_key 引用替换为本地路径（对齐官方 substituteMediaPaths）。"""
    result = content
    for media in mediaList:
        fileKey = media.fileKey
        path = media.path
        if media.resourceType == "image":
            result = result.replace(f"![image]({fileKey})", path)
            # post 富文本里可能写成 ![xxx](img_key)
            result = re.sub(
                rf"!\[([^\]]*)\]\({re.escape(fileKey)}\)",
                path,
                result,
            )
        elif media.resourceType == "sticker":
            result = result.replace(f'<sticker key="{fileKey}"/>', path)
        elif media.resourceType == "file":
            result = re.sub(
                rf'<file key="{re.escape(fileKey)}"[^/]*/>',
                f"[File: {path}]",
                result,
            )
        elif media.resourceType == "audio":
            result = re.sub(
                rf'<audio key="{re.escape(fileKey)}"[^/]*/>',
                f"[Audio: {path}]",
                result,
            )
        elif media.resourceType == "video":
            result = re.sub(
                rf'<video key="{re.escape(fileKey)}"[^/]*/>',
                f"[Video: {path}]",
                result,
            )
    return result


def _InferPlaceholder(resourceType: ResourceType) -> str:
    mapping = {
        "image": "<media:image>",
        "file": "<media:document>",
        "audio": "<media:audio>",
        "video": "<media:video>",
        "sticker": "<media:sticker>",
    }
    return mapping.get(resourceType, "<media:file>")
