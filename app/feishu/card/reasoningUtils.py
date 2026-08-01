"""Reasoning / tool-use 共享工具。"""

from __future__ import annotations

import re

INLINE_ASSIGNMENT_RE = re.compile(r'(^|[\s"\'`])([A-Za-z_][A-Za-z0-9_]*)(=(?:"[^"]*"|\'[^\']*\'|[^\s"\'`]+))')
AUTH_HEADER_SECRET_RE = re.compile(r"(Authorization\s*:\s*(?:Bearer|Basic|Token)\s+)([^'\"\s]+)", re.IGNORECASE)
QUOTED_HEADER_ARG_RE = re.compile(
    r"((?:^|[\s\"'`])(?:-H|--header)\s+)(['\"])([A-Za-z0-9_-]+)(\s*:\s*)([^'\"]*)(\2)",
    re.IGNORECASE,
)
UNQUOTED_HEADER_ARG_RE = re.compile(
    r"((?:^|[\s\"'`])(?:-H|--header)\s+)([A-Za-z0-9_-]+)(\s*:\s*)([^\s\"'`]+)",
    re.IGNORECASE,
)
SECRET_FLAG_RE = re.compile(r"((?:^|[\s\"'`]))(--?[A-Za-z0-9][A-Za-z0-9-]*)(=|\s+)(?:\"([^\"]*)\"|'([^']*)'|([^\s\"'`]+))")
SENSITIVE_NAME_RE = re.compile(
    r"token|secret|password|api[_-]?key|authorization|cookie|credential|bearer|session[_-]?id|client[_-]?secret|access[_-]?key",
    re.IGNORECASE,
)


def NormalizeToolName(name: str | None) -> str:
    return name.strip().lower() if name else ""


def TruncateText(value: str, maxLength: int) -> str:
    if len(value) <= maxLength:
        return value
    return f"{value[: maxLength - 3]}..."


def RedactInlineSecrets(value: str) -> str:
    def _ReplaceAssignment(match: re.Match[str]) -> str:
        prefix = match.group(1)
        key = match.group(2)
        if _IsSensitiveName(key):
            return f"{prefix}{key}=[redacted]"
        return match.group(0)

    result = INLINE_ASSIGNMENT_RE.sub(_ReplaceAssignment, value)
    result = AUTH_HEADER_SECRET_RE.sub(r"\1[redacted]", result)

    def _ReplaceQuotedHeader(match: re.Match[str]) -> str:
        prefix, quote, name, separator = match.group(1), match.group(2), match.group(3), match.group(4)
        if _ShouldRedactHeaderValue(name):
            return f"{prefix}{quote}{name}{separator}[redacted]{quote}"
        return match.group(0)

    result = QUOTED_HEADER_ARG_RE.sub(_ReplaceQuotedHeader, result)

    def _ReplaceUnquotedHeader(match: re.Match[str]) -> str:
        prefix, name, separator = match.group(1), match.group(2), match.group(3)
        if _ShouldRedactHeaderValue(name):
            return f"{prefix}{name}{separator}[redacted]"
        return match.group(0)

    result = UNQUOTED_HEADER_ARG_RE.sub(_ReplaceUnquotedHeader, result)

    def _ReplaceSecretFlag(match: re.Match[str]) -> str:
        prefix, flag, separator = match.group(1), match.group(2), match.group(3)
        normalizedFlag = flag.lstrip("-")
        if not _IsSensitiveName(normalizedFlag):
            return match.group(0)
        doubleQuoted, singleQuoted, bare = match.group(4), match.group(5), match.group(6)
        if doubleQuoted is not None:
            redacted = '"[redacted]"'
        elif singleQuoted is not None:
            redacted = "'[redacted]'"
        elif bare is not None:
            redacted = "[redacted]"
        else:
            redacted = "[redacted]"
        return f"{prefix}{flag}{separator}{redacted}"

    return SECRET_FLAG_RE.sub(_ReplaceSecretFlag, result)


def SanitizeParamsForLog(params: dict[str, object] | None) -> str:
    if not params:
        return ""
    keys = list(params.keys())
    if not keys:
        return "{}"
    return "{" + ",".join(keys) + "}"


def _IsSensitiveName(value: str) -> bool:
    return SENSITIVE_NAME_RE.search(value) is not None


def _ShouldRedactHeaderValue(name: str) -> bool:
    return not re.fullmatch(r"authorization", name, re.IGNORECASE) and _IsSensitiveName(name)
