"""卡片转换工具函数。"""

from __future__ import annotations

from datetime import datetime, timezone


def EscapeAttr(value: str) -> str:
    return value.replace('"', '\\"').replace("\n", "\\n")


def FormatMillisecondsToISO8601(milliseconds: str) -> str:
    try:
        ms = int(milliseconds)
    except ValueError:
        return ""
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat()


def NormalizeTimeFormat(value: str) -> str:
    if not value:
        return ""
    trimmed = value.strip()
    if trimmed.isdigit():
        if len(trimmed) >= 13:
            return FormatMillisecondsToISO8601(trimmed)
        if len(trimmed) >= 10:
            return datetime.fromtimestamp(int(trimmed), tz=timezone.utc).isoformat()
    if trimmed.startswith("20") and "T" in trimmed:
        return trimmed
    if " " in trimmed and trimmed[:4].isdigit():
        try:
            parsed = datetime.fromisoformat(trimmed.replace(" ", "T"))
            return parsed.isoformat()
        except ValueError:
            return trimmed
    return trimmed
