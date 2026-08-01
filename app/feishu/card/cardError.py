"""卡片 API 错误处理与表格降级。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Optional

from app.feishu.core.apiError import ExtractLarkApiCode


@dataclass
class MarkdownTableMatch:
    index: int
    length: int
    raw: str


class CardKitApiError(Exception):
    def __init__(self, api: str, code: int, msg: str, context: str) -> None:
        super().__init__(f"cardkit {api} FAILED: code={code}, msg={msg}, {context}")
        self.code = code
        self.msg = msg


CARD_ERROR_RATE_LIMITED = 230020
CARD_ERROR_CARD_CONTENT_FAILED = 230099
CARD_CONTENT_SUB_ERROR_ELEMENT_LIMIT = 11310
FEISHU_CARD_TABLE_LIMIT = 3


def ExtractSubCode(msg: str) -> Optional[int]:
    match = re.search(r"ErrCode:\s*(\d+)", msg)
    if not match:
        return None
    try:
        return int(match.group(1))
    except ValueError:
        return None


def ParseCardApiError(err: Any) -> Optional[dict[str, Any]]:
    from app.feishu.core.apiError import LarkApiError

    code = ExtractLarkApiCode(err)
    if code is None:
        return None
    errMsg = ""
    if isinstance(err, (CardKitApiError, LarkApiError)):
        errMsg = err.msg
    elif isinstance(err, dict):
        if isinstance(err.get("msg"), str):
            errMsg = err["msg"]
        elif isinstance(err.get("response"), dict):
            responseData = err["response"].get("data")
            if isinstance(responseData, dict) and isinstance(responseData.get("msg"), str):
                errMsg = responseData["msg"]
    elif isinstance(err, BaseException):
        errMsg = str(err)
    subCode = ExtractSubCode(errMsg)
    return {"code": code, "subCode": subCode, "errMsg": errMsg}


def IsCardTableLimitError(err: Any) -> bool:
    parsed = ParseCardApiError(err)
    if parsed is None:
        return False
    return (
        parsed["code"] == CARD_ERROR_CARD_CONTENT_FAILED
        and parsed["subCode"] == CARD_CONTENT_SUB_ERROR_ELEMENT_LIMIT
        and re.search(r"table number over limit", str(parsed["errMsg"]), re.IGNORECASE) is not None
    )


def IsCardRateLimitError(err: Any) -> bool:
    parsed = ParseCardApiError(err)
    if parsed is None:
        return False
    return parsed["code"] == CARD_ERROR_RATE_LIMITED


def FindMarkdownTablesOutsideCodeBlocks(text: str) -> list[MarkdownTableMatch]:
    codeBlockRanges: list[tuple[int, int]] = []
    for match in re.finditer(r"```[\s\S]*?```", text):
        codeBlockRanges.append((match.start(), match.end()))

    def _IsInsideCodeBlock(idx: int) -> bool:
        return any(start <= idx < end for start, end in codeBlockRanges)

    tableRegex = re.compile(r"\|.+\|[\r\n]+\|[-:| ]+\|[\s\S]*?(?=\n\n|\n(?!\|)|$)")
    matches: list[MarkdownTableMatch] = []
    for match in tableRegex.finditer(text):
        if not _IsInsideCodeBlock(match.start()):
            matches.append(MarkdownTableMatch(index=match.start(), length=len(match.group(0)), raw=match.group(0)))
    return matches


def SanitizeTextSegmentsForCard(texts: list[str], tableLimit: int = FEISHU_CARD_TABLE_LIMIT) -> list[str]:
    remainingTableBudget = tableLimit
    result: list[str] = []
    for text in texts:
        tableMatches = FindMarkdownTablesOutsideCodeBlocks(text)
        if len(tableMatches) <= remainingTableBudget:
            remainingTableBudget -= len(tableMatches)
            result.append(text)
            continue
        sanitized = _WrapTablesBeyondLimit(text, tableMatches, max(remainingTableBudget, 0))
        remainingTableBudget = 0
        result.append(sanitized)
    return result


def SanitizeTextForCard(text: str, tableLimit: int = FEISHU_CARD_TABLE_LIMIT) -> str:
    return SanitizeTextSegmentsForCard([text], tableLimit)[0]


def _WrapTablesBeyondLimit(text: str, matches: list[MarkdownTableMatch], keepCount: int) -> str:
    if len(matches) <= keepCount:
        return text
    result = text
    for index in range(len(matches) - 1, keepCount - 1, -1):
        item = matches[index]
        replacement = f"```\n{item.raw}\n```"
        result = result[: item.index] + replacement + result[item.index + item.length :]
    return result
