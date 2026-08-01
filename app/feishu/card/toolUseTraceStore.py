"""Tool-use trace 运行时存储。"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from typing import Literal, Optional

from app.feishu.card.reasoningUtils import NormalizeToolName, RedactInlineSecrets, TruncateText

ToolUseStepStatus = Literal["running", "success", "error"]

TRACE_TTL_MS = 30 * 60 * 1000
MAX_SESSION_TRACES = 128
MAX_STEPS_PER_SESSION = 256
STEP_RUNNING_TIMEOUT_MS = 5 * 60 * 1000
GENERIC_STRING_LIMIT = 512
RESULT_STRING_LIMIT = 1024
COMMAND_STRING_LIMIT = 4096
PATH_STRING_LIMIT = 2048

SENSITIVE_KEY_RE = re.compile(
    r"secret|token|password|authorization|cookie|api[-_]?key|credential|private[-_]?key|access[-_]?key|"
    r"database[-_]?url|connection[-_]?string|bearer|signing[-_]?key|encryption[-_]?key|session[-_]?id|"
    r"client[-_]?secret|auth[-_]?token",
    re.IGNORECASE,
)


@dataclass
class ToolUseTraceStep:
    id: str
    seq: int
    toolName: str
    toolCallId: str | None = None
    runId: str | None = None
    params: dict[str, object] | None = None
    result: object | None = None
    error: str | None = None
    durationMs: float | None = None
    status: ToolUseStepStatus = "running"
    startedAt: float = 0
    finishedAt: float | None = None


@dataclass
class SessionTraceState:
    nextSeq: int = 1
    updatedAt: float = 0
    steps: list[ToolUseTraceStep] = field(default_factory=list)
    currentRunId: str | None = None


_sessionTraces: dict[str, SessionTraceState] = {}


def StartToolUseTraceRun(sessionKey: str) -> None:
    if not sessionKey:
        return
    _PruneTraceStore()
    _sessionTraces[sessionKey] = SessionTraceState(nextSeq=1, updatedAt=time.time() * 1000, steps=[])


def ClearToolUseTraceRun(sessionKey: str) -> None:
    if sessionKey:
        _sessionTraces.pop(sessionKey, None)


def HasToolUseTraceRun(sessionKey: str | None) -> bool:
    return bool(sessionKey and sessionKey in _sessionTraces)


def RecordToolUseStart(
    sessionKey: str | None,
    toolName: str,
    toolParams: dict[str, object] | None = None,
    toolCallId: str | None = None,
    runId: str | None = None,
) -> None:
    if not sessionKey or not toolName:
        return
    state = _sessionTraces.get(sessionKey)
    if state is None:
        return
    if runId:
        if state.currentRunId is None:
            state.currentRunId = runId
        elif state.currentRunId != runId:
            return
    now = time.time() * 1000
    if len(state.steps) >= MAX_STEPS_PER_SESSION:
        state.steps = state.steps[-(MAX_STEPS_PER_SESSION - 1) :]
    state.steps.append(
        ToolUseTraceStep(
            id=str(state.nextSeq),
            seq=state.nextSeq,
            toolName=toolName,
            toolCallId=toolCallId,
            runId=runId,
            params=SanitizeTraceValue(toolParams, source="params"),
            status="running",
            startedAt=now,
        )
    )
    state.nextSeq += 1
    state.updatedAt = now


def RecordToolUseEnd(
    sessionKey: str | None,
    toolName: str,
    toolParams: dict[str, object] | None = None,
    toolCallId: str | None = None,
    runId: str | None = None,
    result: object | None = None,
    error: str | None = None,
    durationMs: float | None = None,
) -> None:
    if not sessionKey or not toolName:
        return
    state = _sessionTraces.get(sessionKey)
    if state is None:
        return
    if runId and state.currentRunId is not None and state.currentRunId != runId:
        return
    now = time.time() * 1000
    sanitizedParams = SanitizeTraceValue(toolParams, source="params")
    pendingIndex = _FindPendingStepIndex(state.steps, toolName, sanitizedParams, toolCallId)
    if pendingIndex >= 0:
        step = state.steps[pendingIndex]
        step.status = "error" if error else "success"
        step.result = SanitizeTraceValue(result, source="result")
        step.error = TruncateText(error, 160) if error else None
        step.durationMs = durationMs
        step.finishedAt = now
        if step.params is None and sanitizedParams:
            step.params = sanitizedParams
        state.updatedAt = now
        return
    state.steps.append(
        ToolUseTraceStep(
            id=str(state.nextSeq),
            seq=state.nextSeq,
            toolName=toolName,
            toolCallId=toolCallId,
            runId=runId,
            params=sanitizedParams,
            result=SanitizeTraceValue(result, source="result"),
            error=TruncateText(error, 160) if error else None,
            durationMs=durationMs,
            status="error" if error else "success",
            startedAt=now,
            finishedAt=now,
        )
    )
    state.nextSeq += 1
    state.updatedAt = now


def GetToolUseTraceSteps(sessionKey: str | None) -> list[ToolUseTraceStep]:
    if not sessionKey:
        return []
    state = _sessionTraces.get(sessionKey)
    if state is None:
        return []
    if time.time() * 1000 - state.updatedAt > TRACE_TTL_MS:
        _sessionTraces.pop(sessionKey, None)
        return []
    now = time.time() * 1000
    result: list[ToolUseTraceStep] = []
    for step in state.steps:
        if step.status == "running" and now - step.startedAt > STEP_RUNNING_TIMEOUT_MS:
            timedOut = ToolUseTraceStep(
                id=step.id,
                seq=step.seq,
                toolName=step.toolName,
                toolCallId=step.toolCallId,
                runId=step.runId,
                params=step.params,
                result=step.result,
                error="timed out",
                durationMs=step.durationMs,
                status="error",
                startedAt=step.startedAt,
                finishedAt=now,
            )
            result.append(timedOut)
        else:
            result.append(step)
    return result


def SanitizeTraceValue(
    value: object | None,
    depth: int = 0,
    source: str = "generic",
    key: str | None = None,
) -> object | None:
    if value is None:
        return None
    if isinstance(value, str):
        limit = _ResolveStringLimit(source, key)
        return TruncateText(_SanitizeTraceString(value, key), limit)
    if isinstance(value, (int, float, bool)):
        return value
    if depth >= 2:
        return "[truncated]"
    if isinstance(value, list):
        return [SanitizeTraceValue(item, depth + 1, source=source) for item in value[:8]]
    if isinstance(value, dict):
        output: dict[str, object] = {}
        for entryKey, entryValue in list(value.items())[:12]:
            output[entryKey] = (
                "[redacted]"
                if _IsSensitiveKey(entryKey)
                else SanitizeTraceValue(entryValue, depth + 1, source=source, key=entryKey)
            )
        return output
    return TruncateText(str(value), 180)


def _FindPendingStepIndex(
    steps: list[ToolUseTraceStep],
    toolName: str,
    params: dict[str, object] | None,
    toolCallId: str | None,
) -> int:
    if toolCallId:
        for index in range(len(steps) - 1, -1, -1):
            step = steps[index]
            if step.status != "running":
                continue
            if step.toolCallId == toolCallId:
                return index
    normalizedToolName = NormalizeToolName(toolName)
    paramsKey = _FingerprintTraceValue(params)
    for index in range(len(steps) - 1, -1, -1):
        step = steps[index]
        if step.status != "running":
            continue
        if NormalizeToolName(step.toolName) != normalizedToolName:
            continue
        if _FingerprintTraceValue(step.params) != paramsKey:
            continue
        return index
    for index in range(len(steps) - 1, -1, -1):
        step = steps[index]
        if step.status != "running":
            continue
        if NormalizeToolName(step.toolName) == normalizedToolName:
            return index
    return -1


def _PruneTraceStore() -> None:
    now = time.time() * 1000
    expired = [key for key, state in _sessionTraces.items() if now - state.updatedAt > TRACE_TTL_MS]
    for key in expired:
        del _sessionTraces[key]
    if len(_sessionTraces) <= MAX_SESSION_TRACES:
        return
    overflow = len(_sessionTraces) - MAX_SESSION_TRACES
    entries = sorted(_sessionTraces.items(), key=lambda item: item[1].updatedAt)
    for key, _ in entries[:overflow]:
        del _sessionTraces[key]


def _SanitizeTraceString(value: str, key: str | None) -> str:
    redactedUrl = re.sub(r"([?&])(api_key|token|secret|key)=[^&]*", r"\1\2=[redacted]", value, flags=re.IGNORECASE)
    if _IsCommandLikeKey(key):
        return RedactInlineSecrets(redactedUrl)
    return redactedUrl


def _ResolveStringLimit(source: str, key: str | None) -> int:
    normalizedKey = (key or "").lower()
    if re.search(r"(?:^|_)(?:command|script|description|prompt|task)(?:$|_)", normalizedKey):
        return COMMAND_STRING_LIMIT
    if re.search(r"(?:^|_)(?:path|file|url|uri|cwd|folder|dir)(?:$|_)", normalizedKey):
        return PATH_STRING_LIMIT
    if source == "result":
        return RESULT_STRING_LIMIT
    return GENERIC_STRING_LIMIT


def _IsCommandLikeKey(key: str | None) -> bool:
    return bool(re.search(r"(?:^|_)(?:command|script)(?:$|_)", (key or "").lower()))


def _IsSensitiveKey(key: str) -> bool:
    return SENSITIVE_KEY_RE.search(key) is not None


def _FingerprintTraceValue(value: object | None) -> str:
    if value is None:
        return ""
    if not isinstance(value, (dict, list)):
        return str(value)
    return json.dumps(_SortTraceValue(value), sort_keys=True)


def _SortTraceValue(value: object) -> object:
    if isinstance(value, list):
        return [_SortTraceValue(item) for item in value]
    if isinstance(value, dict):
        return {key: _SortTraceValue(entry) for key, entry in sorted(value.items(), key=lambda item: item[0])}
    return value
