"""图片 URL 解析（简化版：原样透传）。"""

from __future__ import annotations

from typing import Callable, Optional

from common.cancellationToken import CancellationToken


class ImageResolver:
    def __init__(self, onImageResolved: Callable[[], None]) -> None:
        self._onImageResolved = onImageResolved

    def ResolveImages(self, text: str) -> str:
        return text

    async def ResolveImagesAwaitAsync(
        self,
        text: str,
        timeoutMs: int,
        cancellationToken: Optional[CancellationToken] = None,
    ) -> str:
        if cancellationToken is not None:
            cancellationToken.ThrowIfCancellationRequested()
        return text
