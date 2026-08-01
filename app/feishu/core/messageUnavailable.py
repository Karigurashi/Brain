"""消息不可用（已撤回/已删除）状态管理。"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Awaitable, Callable, Optional, TypeVar

from app.feishu.core.apiError import ExtractLarkApiCode
from app.feishu.core.targets import NormalizeMessageId

T = TypeVar("T")

MESSAGE_RECALLED = 230011
MESSAGE_DELETED = 231003
MESSAGE_TERMINAL_CODES = frozenset({MESSAGE_RECALLED, MESSAGE_DELETED})
UNAVAILABLE_CACHE_TTL_MS = 30 * 60 * 1000
MAX_CACHE_SIZE_BEFORE_PRUNE = 512


@dataclass
class MessageUnavailableState:
    apiCode: int
    markedAtMs: float
    operation: Optional[str] = None


_unavailableMessageCache: dict[str, MessageUnavailableState] = {}


def _PruneExpired(nowMs: Optional[float] = None) -> None:
    now = nowMs if nowMs is not None else time.time() * 1000
    expired = [mid for mid, state in _unavailableMessageCache.items() if now - state.markedAtMs > UNAVAILABLE_CACHE_TTL_MS]
    for mid in expired:
        del _unavailableMessageCache[mid]


def IsTerminalMessageApiCode(code: object) -> bool:
    return isinstance(code, int) and code in MESSAGE_TERMINAL_CODES


def MarkMessageUnavailable(messageId: str, apiCode: int, operation: Optional[str] = None) -> None:
    normalizedId = NormalizeMessageId(messageId)
    if not normalizedId:
        return
    if len(_unavailableMessageCache) >= MAX_CACHE_SIZE_BEFORE_PRUNE:
        _PruneExpired()
    _unavailableMessageCache[normalizedId] = MessageUnavailableState(
        apiCode=apiCode,
        operation=operation,
        markedAtMs=time.time() * 1000,
    )


def GetMessageUnavailableState(messageId: Optional[str]) -> Optional[MessageUnavailableState]:
    normalizedId = NormalizeMessageId(messageId)
    if not normalizedId:
        return None
    state = _unavailableMessageCache.get(normalizedId)
    if state is None:
        return None
    if time.time() * 1000 - state.markedAtMs > UNAVAILABLE_CACHE_TTL_MS:
        del _unavailableMessageCache[normalizedId]
        return None
    return state


def IsMessageUnavailable(messageId: Optional[str]) -> bool:
    return GetMessageUnavailableState(messageId) is not None


def MarkMessageUnavailableFromError(
    messageId: Optional[str],
    error: object,
    operation: Optional[str] = None,
) -> Optional[int]:
    normalizedId = NormalizeMessageId(messageId)
    if not normalizedId:
        return None
    code = ExtractLarkApiCode(error)
    if not IsTerminalMessageApiCode(code):
        return None
    MarkMessageUnavailable(normalizedId, code, operation)
    return code


class MessageUnavailableError(Exception):
    def __init__(self, messageId: str, apiCode: int, operation: Optional[str] = None) -> None:
        operationText = f", op={operation}" if operation else ""
        super().__init__(
            f"[feishu-message-unavailable] message {messageId} unavailable (code={apiCode}{operationText})"
        )
        self.messageId = messageId
        self.apiCode = apiCode
        self.operation = operation


def IsMessageUnavailableError(error: object) -> bool:
    return isinstance(error, MessageUnavailableError)


def AssertMessageAvailable(messageId: Optional[str], operation: Optional[str] = None) -> None:
    normalizedId = NormalizeMessageId(messageId)
    if not normalizedId:
        return
    state = GetMessageUnavailableState(normalizedId)
    if state is None:
        return
    raise MessageUnavailableError(normalizedId, state.apiCode, operation or state.operation)


async def RunWithMessageUnavailableGuardAsync(
    messageId: Optional[str],
    operation: str,
    fn: Callable[[], Awaitable[T]],
) -> T:
    normalizedId = NormalizeMessageId(messageId)
    if not normalizedId:
        return await fn()
    AssertMessageAvailable(normalizedId, operation)
    try:
        return await fn()
    except Exception as error:
        code = MarkMessageUnavailableFromError(normalizedId, error, operation)
        if code is not None:
            raise MessageUnavailableError(normalizedId, code, operation) from error
        raise
