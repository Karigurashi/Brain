"""Reply dispatcher 类型与常量。"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum
from typing import Awaitable, Callable, Optional

from app.feishu.core.types import FeishuConfig, ReplyPayload, ToolUseMode


class ECardPhase(IntEnum):
    IDLE = 0
    CREATING = 1
    STREAMING = 2
    COMPLETED = 3
    ABORTED = 4
    TERMINATED = 5
    CREATION_FAILED = 6


CARD_PHASE_NAMES = {
    ECardPhase.IDLE: "idle",
    ECardPhase.CREATING: "creating",
    ECardPhase.STREAMING: "streaming",
    ECardPhase.COMPLETED: "completed",
    ECardPhase.ABORTED: "aborted",
    ECardPhase.TERMINATED: "terminated",
    ECardPhase.CREATION_FAILED: "creation_failed",
}

TERMINAL_PHASES = frozenset(
    {
        ECardPhase.COMPLETED,
        ECardPhase.ABORTED,
        ECardPhase.TERMINATED,
        ECardPhase.CREATION_FAILED,
    }
)

PHASE_TRANSITIONS: dict[ECardPhase, frozenset[ECardPhase]] = {
    ECardPhase.IDLE: frozenset({ECardPhase.CREATING, ECardPhase.ABORTED, ECardPhase.TERMINATED}),
    ECardPhase.CREATING: frozenset(
        {ECardPhase.STREAMING, ECardPhase.CREATION_FAILED, ECardPhase.ABORTED, ECardPhase.TERMINATED}
    ),
    ECardPhase.STREAMING: frozenset({ECardPhase.COMPLETED, ECardPhase.ABORTED, ECardPhase.TERMINATED}),
    ECardPhase.COMPLETED: frozenset(),
    ECardPhase.ABORTED: frozenset(),
    ECardPhase.TERMINATED: frozenset(),
    ECardPhase.CREATION_FAILED: frozenset(),
}

THROTTLE_CONSTANTS = {
    "CARDKIT_MS": 100,
    # mango 双 element：思考栏单独节流，降低与正文并发刷卡导致的 230020
    "REASONING_CARDKIT_MS": 400,
    "PATCH_MS": 1500,
    "LONG_GAP_THRESHOLD_MS": 2000,
    "BATCH_AFTER_GAP_MS": 300,
    "REASONING_STATUS_MS": 1500,
    # 工具区整卡重建节流；步数变化时强制刷新，不受此限制
    "TOOL_STATUS_MS": 400,
}

EMPTY_REPLY_FALLBACK_TEXT = "Done."
TerminalReason = str


@dataclass
class ReasoningState:
    accumulatedReasoningText: str = ""
    reasoningStartTime: float | None = None
    reasoningElapsedMs: float = 0
    isReasoningPhase: bool = False


@dataclass
class ToolUseState:
    startedAt: float | None = None
    elapsedMs: float = 0
    isActive: bool = False


@dataclass
class StreamingTextState:
    accumulatedText: str = ""
    completedText: str = ""
    streamingPrefix: str = ""
    lastPartialText: str = ""
    lastFlushedText: str = ""


@dataclass
class CardKitState:
    cardKitCardId: str | None = None
    originalCardKitCardId: str | None = None
    cardKitSequence: int = 0
    cardMessageId: str | None = None


@dataclass
class FooterSessionMetrics:
    inputTokens: int | None = None
    outputTokens: int | None = None
    cacheHitRate: float | None = None  # 0-100，与 CLI GetLastCacheHitRate 一致
    cacheRead: int | None = None
    cacheWrite: int | None = None
    totalTokens: int | None = None
    totalTokensFresh: bool | None = None
    contextTokens: int | None = None
    model: str | None = None


@dataclass
class ToolUseDisplayConfig:
    mode: ToolUseMode = "off"
    showToolUse: bool = False
    showToolResultDetails: bool = False
    showFullPaths: bool = False


FooterMetricsProvider = Callable[[], Awaitable[FooterSessionMetrics | None]]


@dataclass
class StreamingCardDeps:
    client: object
    agentId: str
    sessionKey: str
    accountId: str | None
    chatId: str
    replyToMessageId: str | None
    toolUseDisplay: ToolUseDisplayConfig
    resolvedFooter: dict[str, bool]
    getFooterMetrics: FooterMetricsProvider | None = None


@dataclass
class CreateFeishuReplyDispatcherParams:
    credentials: object
    feishuCfg: FeishuConfig | None
    agentId: str
    sessionKey: str
    chatId: str
    replyToMessageId: str | None = None
    accountId: str | None = None
    chatType: str | None = None
    skipTyping: bool = False
    toolUseDisplay: ToolUseDisplayConfig = field(default_factory=ToolUseDisplayConfig)
    getFooterMetrics: FooterMetricsProvider | None = None
    textChunkLimit: int = 4000


@dataclass
class ReplyDispatcherCallbacks:
    deliver: Callable[..., Awaitable[None]]
    onError: Callable[..., Awaitable[None]]
    onIdle: Callable[..., Awaitable[None]]
    onReplyStart: Callable[..., Awaitable[None]]
    onCleanup: Callable[..., Awaitable[None]]


@dataclass
class FeishuReplyDispatcherResult:
    dispatcher: ReplyDispatcherCallbacks
    replyOptions: dict[str, object]
    markDispatchIdle: Callable[[], None]
    markFullyComplete: Callable[[], None]
    abortCard: Callable[[], Awaitable[None]]
