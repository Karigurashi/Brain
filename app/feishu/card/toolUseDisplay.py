"""Tool-use 结构化展示。"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Literal, Optional
from urllib.parse import urlparse, urlunparse

from app.feishu.card.markdownStyle import OptimizeMarkdownStyle
from app.feishu.card.reasoningUtils import NormalizeToolName, RedactInlineSecrets
from app.feishu.card.toolUseTraceStore import ToolUseTraceStep

ToolUseStepStatus = Literal["running", "success", "error"]
EMPTY_TOOL_USE_PLACEHOLDER = "No tool steps available"
# 折叠面板体内最多展示最近 N 条；stepCount 仍为总数
MAX_VISIBLE_TOOL_STEPS = 10


@dataclass
class ToolUseDisplayBlock:
    language: Literal["json", "text"]
    content: str


@dataclass
class ToolUseDisplayStep:
    title: str
    iconToken: str
    status: ToolUseStepStatus
    detail: str | None = None
    resultBlock: ToolUseDisplayBlock | None = None
    errorBlock: ToolUseDisplayBlock | None = None


@dataclass
class ToolUseDisplayResult:
    content: str
    stepCount: int
    steps: list[ToolUseDisplayStep]


@dataclass
class _ToolDescriptor:
    """aliases 使用 NormalizeToolName 后的值（lower），与 mangoAgent BaseTool.name 对齐。"""

    aliases: list[str]
    iconToken: str
    title: str
    sanitizer: str
    paramKeys: list[str] | None = None
    summaryPatterns: list[re.Pattern[str]] | None = None
    summaryPreference: list[str] | None = None


# 与 agent/component/tool 下注册工具一一对应；MCP 动态工具用 mcp_ 前缀兜底。
_TOOL_DESCRIPTORS: list[_ToolDescriptor] = [
    # File
    _ToolDescriptor(["read"], "file-link-text_outlined", "Read", "path", ["file_path"]),
    _ToolDescriptor(["write"], "edit_outlined", "Write", "path", ["file_path"]),
    _ToolDescriptor(["searchreplace"], "edit_outlined", "Search replace", "path", ["file_path"]),
    _ToolDescriptor(["deletefile"], "edit_outlined", "Delete file", "path", ["file_path"]),
    _ToolDescriptor(["grep"], "doc-search_outlined", "Grep", "generic", ["regex", "path"]),
    _ToolDescriptor(["glob"], "folder_outlined", "Glob", "generic", ["query", "path"]),
    # Shell
    _ToolDescriptor(["shell"], "setting_outlined", "Shell", "command", ["command"]),
    _ToolDescriptor(["getterminaloutput"], "setting_outlined", "Terminal output", "generic", ["terminal_id"]),
    # Network
    _ToolDescriptor(["websearch"], "search_outlined", "Web search", "search", ["query"]),
    _ToolDescriptor(["webfetch"], "language_outlined", "Web fetch", "url", ["url"]),
    # Internal
    _ToolDescriptor(["skill"], "app-default_outlined", "Load Skill", "skill", ["command"]),
    _ToolDescriptor(["todowrite"], "list-check_outlined", "Todo", "generic", ["todos"]),
    _ToolDescriptor(["reload"], "setting-inter_outlined", "Reload", "generic"),
    # Task
    _ToolDescriptor(["listtasks"], "list-check_outlined", "List tasks", "generic", ["taskType"]),
    _ToolDescriptor(["createscheduletask"], "robot_outlined", "Create schedule", "generic", ["name", "expression"]),
    _ToolDescriptor(["deletetask"], "robot_outlined", "Delete task", "generic", ["taskId"]),
    _ToolDescriptor(["runflowtask"], "robot_outlined", "Run workflow", "generic"),
    _ToolDescriptor(["getflowschema"], "robot_outlined", "Flow schema", "generic"),
    # MCP: mcp_{server}_{tool}
    _ToolDescriptor(["mcp"], "app-default_outlined", "MCP", "generic"),
]


def NormalizeToolUseDisplay(
    traceSteps: list[ToolUseTraceStep] | None = None,
    showFullPaths: bool = False,
    showResultDetails: bool = False,
) -> ToolUseDisplayResult:
    steps = [
        step
        for step in (_FormatToolStep(_ToTraceSource(item), showFullPaths, showResultDetails) for item in (traceSteps or []))
        if step is not None
    ]
    totalCount = len(steps)
    visibleSteps = steps[-MAX_VISIBLE_TOOL_STEPS:] if totalCount > MAX_VISIBLE_TOOL_STEPS else steps
    content = "\n".join(
        f"- {s.title}: {s.detail}" if s.detail else f"- {s.title}" for s in visibleSteps
    )
    return ToolUseDisplayResult(content=content, stepCount=totalCount, steps=visibleSteps)


def BuildToolUseTitleSuffix(stepCount: int) -> dict[str, str]:
    """折叠栏副标题：对齐 openclaw-lark-main。"""
    return {
        "zh": f"查看 {stepCount} 个步骤",
        "en": f"Show {stepCount} step{'s' if stepCount != 1 else ''}",
    }


def _ToTraceSource(step: ToolUseTraceStep) -> dict[str, object]:
    return {
        "toolName": step.toolName,
        "params": step.params,
        "result": step.result,
        "error": step.error,
        "durationMs": step.durationMs,
        "status": step.status,
    }


def _FormatToolStep(source: dict[str, object], showFullPaths: bool, showResultDetails: bool) -> ToolUseDisplayStep | None:
    toolName = str(source.get("toolName") or "tool")
    descriptor = _ResolveToolDescriptor(toolName)
    params = source.get("params") if isinstance(source.get("params"), dict) else None
    rawDetail = None
    if descriptor:
        rawDetail = _ExtractDetailFromParams(params, descriptor)
    if not rawDetail and descriptor and descriptor.title == "MCP":
        rawDetail = _ExtractFirstScalarParam(params)
    if not rawDetail and descriptor:
        rawDetail = _ExtractDetailFromSummary(None, descriptor)
    detail = _SanitizeToolDetail(descriptor.sanitizer if descriptor else "generic", rawDetail, showFullPaths) if rawDetail else None
    title = _BuildToolTitle(source, descriptor, rawDetail)
    status = _ResolveStepStatus(source)
    error = source.get("error")
    errorBlock = _BuildErrorBlock(str(error), descriptor) if error else None
    resultBlock = None
    if not errorBlock and showResultDetails:
        resultBlock = _BuildResultBlock(source, descriptor)
    return ToolUseDisplayStep(
        title=title,
        detail=detail,
        iconToken=descriptor.iconToken if descriptor else "setting-inter_outlined",
        status=status,
        resultBlock=resultBlock,
        errorBlock=errorBlock,
    )


def _BuildToolTitle(source: dict[str, object], descriptor: _ToolDescriptor | None, rawDetail: str | None) -> str:
    toolName = str(source.get("toolName") or "tool")
    if descriptor and descriptor.title == "MCP":
        baseTitle = _HumanizeToolName(toolName)
    else:
        baseTitle = descriptor.title if descriptor else _HumanizeToolName(toolName)
    if descriptor and descriptor.title == "Read" and rawDetail and _IsSkillPathValue(rawDetail):
        baseTitle = "Skill Read"
    durationMs = source.get("durationMs")
    if isinstance(durationMs, (int, float)):
        return f"{baseTitle} ({_FormatDurationLabel(float(durationMs))})"
    return baseTitle


def _ResolveToolDescriptor(toolName: str) -> _ToolDescriptor | None:
    normalizedName = NormalizeToolName(toolName)
    for descriptor in _TOOL_DESCRIPTORS:
        if normalizedName in descriptor.aliases:
            return descriptor
    # 前缀匹配：mcp_xxx 等动态工具
    for descriptor in _TOOL_DESCRIPTORS:
        for alias in descriptor.aliases:
            if normalizedName.startswith(f"{alias}_") or normalizedName.startswith(f"{alias}-"):
                return descriptor
    return None


def _ExtractDetailFromParams(params: dict[str, object] | None, descriptor: _ToolDescriptor) -> str | None:
    if not params:
        return None
    for key in descriptor.paramKeys or []:
        text = _ExtractParamDetail(key, params.get(key))
        if text:
            return text
    return None


def _ExtractParamDetail(key: str, value: object) -> str | None:
    if key == "todos" and isinstance(value, list):
        count = len(value)
        if count == 0:
            return "0 items"
        first = value[0] if isinstance(value[0], dict) else None
        firstContent = _ExtractScalarText(first.get("content")) if first else None
        suffix = "" if count == 1 else "s"
        if firstContent:
            return f"{count} item{suffix}: {firstContent}"
        return f"{count} item{suffix}"
    if key == "taskType":
        if isinstance(value, (int, float)):
            return {1: "SCHEDULED", 2: "WORKFLOW"}.get(int(value), str(int(value)))
        text = _ExtractScalarText(value)
        return text
    return _ExtractScalarText(value)


def _ExtractDetailFromSummary(summaryText: str | None, descriptor: _ToolDescriptor) -> str | None:
    if not summaryText:
        return None
    for line in summaryText.replace("\r\n", "\n").split("\n"):
        cleaned = _CleanupLine(_StripMarkdown(line))
        if not cleaned or _IsNoiseLine(cleaned):
            continue
        for pattern in descriptor.summaryPatterns or []:
            match = pattern.search(cleaned)
            if match and match.group(1):
                return match.group(1).strip()
    return None


def _ResolveStepStatus(source: dict[str, object]) -> ToolUseStepStatus:
    if source.get("error"):
        return "error"
    status = source.get("status")
    if status in ("running", "success", "error"):
        return status  # type: ignore[return-value]
    return "success"


def _BuildResultBlock(source: dict[str, object], descriptor: _ToolDescriptor | None) -> ToolUseDisplayBlock | None:
    result = source.get("result")
    if result is None:
        return None
    # 大内容工具默认不展开结果块
    if descriptor and descriptor.title in ("Read", "Write", "Search replace", "Web fetch", "Grep", "Glob"):
        return None
    return _BuildDisplayBlock(_SanitizeDisplayBlockValue(result, descriptor))


def _BuildErrorBlock(error: str, descriptor: _ToolDescriptor | None) -> ToolUseDisplayBlock | None:
    return _BuildDisplayBlock(_SanitizeDisplayBlockValue(error, descriptor), "text")


def _SanitizeDisplayBlockValue(value: object, descriptor: _ToolDescriptor | None) -> object:
    if descriptor and descriptor.sanitizer == "command" and isinstance(value, str):
        return RedactInlineSecrets(value)
    return value


def _BuildDisplayBlock(value: object, fallbackLanguage: Literal["json", "text"] = "json") -> ToolUseDisplayBlock | None:
    if value is None:
        return None
    if isinstance(value, str):
        normalized = value.replace("\r\n", "\n").strip()
        if not normalized:
            return None
        parsed = _TryParseJson(normalized)
        if isinstance(parsed, (dict, list)):
            pretty = json.dumps(parsed, indent=2, ensure_ascii=False)
            return ToolUseDisplayBlock(language="json", content=pretty)
        language: Literal["json", "text"] = "text" if fallbackLanguage == "json" else fallbackLanguage
        return ToolUseDisplayBlock(language=language, content=normalized)
    if isinstance(value, (dict, list)):
        return ToolUseDisplayBlock(language="json", content=json.dumps(value, indent=2, ensure_ascii=False))
    normalized = str(value).strip()
    return ToolUseDisplayBlock(language="text", content=normalized) if normalized else None


def _SanitizeToolDetail(kind: str, value: str, showFullPaths: bool) -> str | None:
    if kind == "command":
        cleaned = re.sub(r"\s+", " ", value).strip()
        if not cleaned:
            return None
        redacted = RedactInlineSecrets(cleaned)
        return redacted if showFullPaths else _RedactCommandPaths(redacted)
    cleaned = _SanitizeGenericText(value)
    if not cleaned:
        return None
    if kind == "skill":
        return re.sub(r"[-_]+", " ", re.sub(r"^skill\s+", "", cleaned, flags=re.I)).strip() or "skill"
    if kind == "path":
        return _SanitizePathLike(cleaned, showFullPaths)
    if kind == "search":
        return cleaned.strip("'\"")
    if kind == "url":
        return re.sub(r"^from\s+", "", cleaned.strip("'\""), flags=re.I)
    return cleaned


def _SanitizePathLike(value: str, showFullPaths: bool) -> str:
    cleaned = re.sub(r"^(?:from|file|path)\s+", "", _SanitizeGenericText(value), flags=re.I).strip()
    if showFullPaths:
        return cleaned
    skillMatch = re.search(r"(?:^|/)skills/([^/]+)/", cleaned, re.I)
    if skillMatch:
        return re.sub(r"[-_]+", " ", skillMatch.group(1)).strip() or cleaned
    segments = [segment for segment in re.split(r"[\\/]", cleaned) if segment]
    return segments[-1] if segments else cleaned


def _RedactCommandPaths(command: str) -> str:
    parts = re.split(r"(\s+)", command)
    return "".join(_RedactCommandToken(part) if part and not part.isspace() else part for part in parts)


def _RedactCommandToken(token: str) -> str:
    match = re.match(r'^([("\'`]*)(.*?)([)"\'`,;:]*)$', token)
    if not match:
        return token
    prefix, core, suffix = match.group(1), match.group(2), match.group(3)
    if "=" in core:
        left, right = core.split("=", 1)
        return f"{prefix}{left}={_RedactStandalonePath(right)}{suffix}"
    return f"{prefix}{_RedactStandalonePath(core)}{suffix}"


def _RedactStandalonePath(value: str) -> str:
    if re.match(r"^https?://", value, re.I):
        return _SanitizeUrlForDisplay(value)
    if value.startswith(("~/", "./", "../", "/")) or "/" in value:
        segments = [segment for segment in value.replace("\\", "/").rstrip("/").split("/") if segment]
        return segments[-1] if segments else value
    return value


def _SanitizeUrlForDisplay(url: str) -> str:
    try:
        parsed = urlparse(url)
        queryPairs = []
        for key, val in re.findall(r"([^=&]+)=([^&]*)", parsed.query):
            if re.search(r"(secret|token|password|key|credential|bearer|auth)", key, re.I):
                val = "[redacted]"
            queryPairs.append(f"{key}={val}")
        newQuery = "&".join(queryPairs)
        return urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, newQuery, parsed.fragment))
    except Exception:
        return url


def _IsSkillPathValue(value: str) -> bool:
    return re.search(r"(?:^|/)skills/[^/]+/", value, re.I) is not None


def _SanitizeGenericText(value: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", value)).strip()


def _CleanupLine(line: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"^\d+[.)]\s*", "", re.sub(r"^[-*•]\s*", "", line))).strip()


def _StripMarkdown(line: str) -> str:
    line = re.sub(r"`([^`]+)`", r"\1", line)
    line = re.sub(r"\*\*([^*]+)\*\*", r"\1", line)
    line = re.sub(r"\*([^*]+)\*", r"\1", line)
    return re.sub(r"^>\s*", "", line).strip()


def _IsNoiseLine(line: str) -> bool:
    return bool(re.fullmatch(r"(?:completed|complete|done|success|succeeded|running|started|finished|ok)", line, re.I))


def _HumanizeToolName(name: str) -> str:
    cleaned = re.sub(r"[-_]+", " ", name).strip()
    return cleaned[:1].upper() + cleaned[1:] if cleaned else "Tool"


def _FormatDurationLabel(durationMs: float) -> str:
    return f"{int(durationMs)} ms" if durationMs < 1000 else f"{durationMs / 1000:.1f} s"


def _ExtractScalarText(value: object) -> str | None:
    if isinstance(value, str):
        trimmed = value.strip()
        return trimmed or None
    if isinstance(value, (int, float, bool)):
        return str(value)
    return None


def _ExtractFirstScalarParam(params: dict[str, object] | None) -> str | None:
    if not params:
        return None
    for value in params.values():
        text = _ExtractScalarText(value)
        if text:
            return text
    return None


def _TryParseJson(value: str) -> object | None:
    trimmed = value.strip()
    if not trimmed or not re.match(r"^(?:\{|\[)", trimmed):
        return None
    try:
        return json.loads(trimmed)
    except json.JSONDecodeError:
        return None
