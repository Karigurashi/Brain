"""消息不可用守卫。"""

from __future__ import annotations

from typing import Callable, Optional

from app.feishu.core.apiError import ExtractLarkApiCode
from app.feishu.core.messageUnavailable import (
    GetMessageUnavailableState,
    IsMessageUnavailable,
    IsMessageUnavailableError,
    IsTerminalMessageApiCode,
    MarkMessageUnavailable,
)
from common.logger import Logger


class UnavailableGuard:
    def __init__(
        self,
        replyToMessageId: str | None,
        getCardMessageId: Callable[[], str | None],
        onTerminate: Callable[[], None],
    ) -> None:
        self._replyToMessageId = replyToMessageId
        self._getCardMessageId = getCardMessageId
        self._onTerminate = onTerminate
        self._terminated = False

    @property
    def IsTerminated(self) -> bool:
        return self._terminated

    def ShouldSkip(self, source: str) -> bool:
        if self._terminated:
            return True
        if not self._replyToMessageId:
            return False
        if not IsMessageUnavailable(self._replyToMessageId):
            return False
        return self.Terminate(source)

    def Terminate(self, source: str, err: object | None = None) -> bool:
        if self._terminated:
            return True

        fromError = err if IsMessageUnavailableError(err) else None
        cardMessageId = self._getCardMessageId()
        state = GetMessageUnavailableState(self._replyToMessageId) or GetMessageUnavailableState(cardMessageId)
        apiCode = fromError.apiCode if fromError is not None else (state.apiCode if state else None)

        if apiCode is None and err is not None:
            detectedCode = ExtractLarkApiCode(err)
            if IsTerminalMessageApiCode(detectedCode):
                fallbackMessageId = self._replyToMessageId or cardMessageId
                if fallbackMessageId:
                    MarkMessageUnavailable(fallbackMessageId, detectedCode, source)
                apiCode = detectedCode
        if apiCode is None:
            return False

        self._terminated = True
        self._onTerminate()
        affectedMessageId = (
            fromError.messageId if fromError is not None else (self._replyToMessageId or cardMessageId or "unknown")
        )
        Logger.Warning(
            f"reply pipeline terminated by unavailable message source={source} apiCode={apiCode} messageId={affectedMessageId}"
        )
        return True
