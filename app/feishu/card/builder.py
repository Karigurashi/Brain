"""飞书交互卡片构建。"""

from __future__ import annotations

import re
from typing import Literal, Optional

from app.feishu.card.markdownStyle import CompactMarkdownBlankLines, OptimizeMarkdownStyle
from app.feishu.card.reasoningUtils import TruncateText
from app.feishu.card.replyDispatcherTypes import FooterSessionMetrics
from app.feishu.card.toolUseDisplay import (
    EMPTY_TOOL_USE_PLACEHOLDER,
    ToolUseDisplayStep,
    ToolUseStepStatus,
)

STREAMING_ELEMENT_ID = "streaming_content"
REASONING_ELEMENT_ID = "reasoning_content"
TOOL_USE_STEP_CONTENT_INDENT = "0px 0px 0px 22px"
MAX_REASONING_DISPLAY_CHARS = 500
MAX_TOOL_DETAIL_LINE_CHARS = 80

CardState = Literal["thinking", "streaming", "complete", "confirm"]
REASONING_PREFIX = "Reasoning:\n"


def TruncateReasoningForDisplay(text: str | None) -> str:
    """思考区展示文本：去多余空行后最多 500 字符，超出以 ... 结尾。"""
    if not text:
        return ""
    return TruncateText(CompactMarkdownBlankLines(text), MAX_REASONING_DISPLAY_CHARS)


def SplitReasoningText(text: str | None) -> dict[str, str | None]:
    if not text or not text.strip():
        return {}
    trimmed = text.strip()
    if trimmed.startswith(REASONING_PREFIX) and len(trimmed) > len(REASONING_PREFIX):
        return {"reasoningText": _CleanReasoningPrefix(trimmed)}
    taggedReasoning = _ExtractThinkingContent(text)
    strippedAnswer = StripReasoningTags(text)
    if not taggedReasoning and strippedAnswer == text:
        return {"answerText": text}
    return {"reasoningText": taggedReasoning or None, "answerText": strippedAnswer or None}


def StripReasoningTags(text: str) -> str:
    result = re.sub(
        r"<\s*(?:think(?:ing)?|thought|antthinking)\s*>[\s\S]*?<\s*/\s*(?:think(?:ing)?|thought|antthinking)\s*>",
        "",
        text,
        flags=re.IGNORECASE,
    )
    result = re.sub(r"<\s*(?:think(?:ing)?|thought|antthinking)\s*>[\s\S]*$", "", result, flags=re.IGNORECASE)
    result = re.sub(r"<\s*/\s*(?:think(?:ing)?|thought|antthinking)\s*>", "", result, flags=re.IGNORECASE)
    return result.strip()


def FormatReasoningDuration(ms: float) -> dict[str, str]:
    duration = FormatElapsed(ms)
    return {"zh": f"思考了 {duration}", "en": f"Thought for {duration}"}


def FormatToolUseDuration(ms: float) -> dict[str, str]:
    duration = FormatElapsed(ms)
    return {"zh": f"执行耗时 {duration}", "en": f"Tool use for {duration}"}


def FormatElapsed(ms: float) -> str:
    seconds = ms / 1000
    if seconds < 60:
        return f"{seconds:.1f}s"
    return f"{int(seconds // 60)}m {round(seconds % 60)}s"


def CompactNumber(value: float) -> str:
    absValue = abs(value)
    if absValue >= 1_000_000:
        scaled = value / 1_000_000
        return f"{round(scaled)}m" if abs(scaled) >= 100 else f"{scaled:.1f}m"
    if absValue >= 1_000:
        scaled = value / 1_000
        return f"{round(scaled)}k" if abs(scaled) >= 100 else f"{scaled:.1f}k"
    return str(round(value))


def FormatTokenK(value: int) -> str:
    """与 CLI CliConfig.FormatK 一致：token → x.xk。"""
    return f"{max(0, value) / 1000.0:.1f}k"


def FormatFooterRuntimeSegments(
    footer: dict[str, bool] | None,
    metrics: FooterSessionMetrics | None,
    elapsedMs: float | None = None,
    isError: bool = False,
    isAborted: bool = False,
) -> dict[str, list[str]]:
    """底脚单行：📊 输入107.4k · 输出0.2k · 缓存命中 0.0% · ⏱️ 41.1s

    数据语义对齐 CLI PrintUsageFooter（GetLastTokenUsage）。
    """
    enabled = footer or {}
    showTokens = enabled.get("tokens", True)
    showCache = enabled.get("cache", True)
    showElapsed = enabled.get("elapsed", True)
    showStatus = enabled.get("status", False)

    parts: list[str] = []
    if showStatus:
        if isError:
            parts.append("出错")
        elif isAborted:
            parts.append("已停止")

    if showTokens and metrics is not None:
        inTokens = metrics.inputTokens if isinstance(metrics.inputTokens, int) else 0
        outTokens = metrics.outputTokens if isinstance(metrics.outputTokens, int) else 0
        if inTokens > 0 or outTokens > 0:
            parts.append(f"📊 输入{FormatTokenK(inTokens)}")
            parts.append(f"输出{FormatTokenK(outTokens)}")

    if showCache and metrics is not None:
        rate = metrics.cacheHitRate
        if isinstance(rate, (int, float)):
            parts.append(f"缓存命中 {float(rate):.1f}%")

    if showElapsed and elapsedMs is not None:
        parts.append(f"⏱️ {FormatElapsed(elapsedMs)}")

    if not parts:
        return {"primaryZh": [], "primaryEn": [], "detailZh": [], "detailEn": []}
    line = " · ".join(parts)
    return {"primaryZh": [line], "primaryEn": [line], "detailZh": [], "detailEn": []}


def BuildCardContent(
    state: CardState,
    text: str = "",
    reasoningText: str | None = None,
    reasoningElapsedMs: float | None = None,
    toolUseSteps: list[ToolUseDisplayStep] | None = None,
    toolUseStepCount: int | None = None,
    toolUseTitleSuffix: dict[str, str] | None = None,
    toolUseElapsedMs: float | None = None,
    showToolUse: bool = True,
    confirmData: dict[str, str] | None = None,
    elapsedMs: float | None = None,
    isError: bool = False,
    isAborted: bool = False,
    footer: dict[str, bool] | None = None,
    footerMetrics: FooterSessionMetrics | None = None,
) -> dict[str, object]:
    if state == "thinking":
        return _BuildThinkingCard()
    if state == "streaming":
        return _BuildStreamingCard(
            text,
            reasoningText=reasoningText,
            showToolUse=showToolUse,
            toolUseSteps=toolUseSteps,
            toolUseStepCount=toolUseStepCount,
            toolUseTitleSuffix=toolUseTitleSuffix,
        )
    if state == "complete":
        return _BuildCompleteCard(
            text=text,
            elapsedMs=elapsedMs,
            isError=isError,
            reasoningText=reasoningText,
            reasoningElapsedMs=reasoningElapsedMs,
            toolUseSteps=toolUseSteps,
            toolUseStepCount=toolUseStepCount,
            toolUseTitleSuffix=toolUseTitleSuffix,
            toolUseElapsedMs=toolUseElapsedMs,
            showToolUse=showToolUse,
            isAborted=isAborted,
            footer=footer,
            footerMetrics=footerMetrics,
        )
    if state == "confirm" and confirmData:
        return _BuildConfirmCard(confirmData)
    raise ValueError(f"Unknown card state: {state}")


def BuildStreamingThinkingCard(showToolUse: bool = True) -> dict[str, object]:
    return BuildStreamingPreAnswerCard(showToolUse=showToolUse)


def BuildStreamingPreAnswerCard(
    steps: list[ToolUseDisplayStep] | None = None,
    elapsedMs: float | None = None,
    showToolUse: bool = True,
    totalStepCount: int | None = None,
    reasoningText: str = "",
    answerText: str = "",
    includeReasoning: bool = False,
) -> dict[str, object]:
    """流式预回答卡：有工具步骤才挂工具区；有思考时才挂折叠思考区。"""
    elements: list[dict[str, object]] = []
    # 无步骤不渲染 pending/占位，避免「没用工具也显示工具」
    if showToolUse and steps:
        elements.append(
            _BuildStreamingToolUseActivePanel(steps, elapsedMs, totalStepCount=totalStepCount)
        )
    # 思考从首次出现起就在折叠面板内（禁止与正文并排开放 markdown）
    if includeReasoning or bool(reasoningText and reasoningText.strip()):
        elements.append(
            _BuildStreamingReasoningPanel(
                TruncateReasoningForDisplay(reasoningText) if reasoningText else ""
            )
        )
    elements.extend(
        [
            {
                "tag": "markdown",
                "content": OptimizeMarkdownStyle(answerText) if answerText else "",
                "text_align": "left",
                "text_size": "normal_v2",
                "margin": "0px 0px 0px 0px",
                "element_id": STREAMING_ELEMENT_ID,
            },
            {
                "tag": "markdown",
                "content": " ",
                "icon": {
                    "tag": "custom_icon",
                    "img_key": "img_v3_02vb_496bec09-4b43-4773-ad6b-0cdd103cd2bg",
                    "size": "16px 16px",
                },
                "element_id": "loading_icon",
            },
        ]
    )
    return {
        "schema": "2.0",
        "config": {
            "streaming_mode": True,
            "locales": ["zh_cn", "en_us"],
            "summary": {
                "content": "Processing...",
                "i18n_content": {"zh_cn": "处理中...", "en_us": "Processing..."},
            },
        },
        "body": {"elements": elements},
    }


def ToCardKit2(card: dict[str, object]) -> dict[str, object]:
    result: dict[str, object] = {
        "schema": "2.0",
        "config": card.get("config", {}),
        "body": {"elements": card.get("elements", [])},
    }
    if card.get("header"):
        result["header"] = card["header"]
    return result


def _BuildThinkingCard() -> dict[str, object]:
    return {
        "config": {"wide_screen_mode": True, "update_multi": True, "locales": ["zh_cn", "en_us"]},
        "elements": [
            {
                "tag": "markdown",
                "content": "Thinking...",
                "i18n_content": {"zh_cn": "思考中...", "en_us": "Thinking..."},
            }
        ],
    }


def _BuildStreamingCard(
    partialText: str,
    reasoningText: str | None = None,
    showToolUse: bool = True,
    toolUseSteps: list[ToolUseDisplayStep] | None = None,
    toolUseStepCount: int | None = None,
    toolUseTitleSuffix: dict[str, str] | None = None,
) -> dict[str, object]:
    elements: list[dict[str, object]] = []
    if showToolUse and toolUseSteps:
        elements.append(
            _BuildToolUsePanel(
                toolUseSteps,
                titleSuffix=toolUseTitleSuffix,
                totalStepCount=toolUseStepCount,
            )
        )
    displayReasoning = TruncateReasoningForDisplay(reasoningText)
    if displayReasoning:
        elements.append(_BuildStreamingReasoningPanel(displayReasoning, withElementId=False))
    if partialText:
        elements.append({"tag": "markdown", "content": OptimizeMarkdownStyle(partialText)})
    return {"config": {"wide_screen_mode": True, "update_multi": True, "locales": ["zh_cn", "en_us"]}, "elements": elements}


def _BuildCompleteCard(
    text: str,
    elapsedMs: float | None,
    isError: bool,
    reasoningText: str | None,
    reasoningElapsedMs: float | None,
    toolUseSteps: list[ToolUseDisplayStep] | None,
    toolUseStepCount: int | None,
    toolUseTitleSuffix: dict[str, str] | None,
    toolUseElapsedMs: float | None,
    showToolUse: bool,
    isAborted: bool,
    footer: dict[str, bool] | None,
    footerMetrics: FooterSessionMetrics | None,
) -> dict[str, object]:
    elements: list[dict[str, object]] = []
    if showToolUse and toolUseSteps:
        elements.append(
            _BuildToolUsePanel(
                toolUseSteps,
                toolUseElapsedMs,
                toolUseTitleSuffix,
                totalStepCount=toolUseStepCount,
            )
        )
    displayReasoning = TruncateReasoningForDisplay(reasoningText)
    if displayReasoning:
        duration = FormatReasoningDuration(reasoningElapsedMs) if reasoningElapsedMs else None
        zhLabel = duration["zh"] if duration else "思考"
        enLabel = duration["en"] if duration else "Thought"
        elements.append(
            {
                "tag": "collapsible_panel",
                "expanded": False,
                "header": {
                    "title": {
                        "tag": "markdown",
                        "content": f"💭 {enLabel}",
                        "i18n_content": {"zh_cn": f"💭 {zhLabel}", "en_us": f"💭 {enLabel}"},
                    },
                    "vertical_align": "center",
                    "icon": {"tag": "standard_icon", "token": "down-small-ccm_outlined", "size": "16px 16px"},
                    "icon_position": "follow_text",
                    "icon_expanded_angle": -180,
                },
                "border": {"color": "grey", "corner_radius": "5px"},
                "vertical_spacing": "8px",
                "padding": "8px 8px 8px 8px",
                "elements": [{"tag": "markdown", "content": displayReasoning, "text_size": "notation"}],
            }
        )
    elements.append({"tag": "markdown", "content": OptimizeMarkdownStyle(text)})
    footerSegments = FormatFooterRuntimeSegments(footer, footerMetrics, elapsedMs, isError, isAborted)
    footerLineZh = footerSegments["primaryZh"][0] if footerSegments["primaryZh"] else ""
    footerLineEn = footerSegments["primaryEn"][0] if footerSegments["primaryEn"] else footerLineZh
    if footerLineZh:
        elements.extend(_BuildFooter(footerLineZh, footerLineEn, isError or isAborted))
    summaryText = re.sub(r"[*_`#>\[\]()~]", "", text).strip()
    config: dict[str, object] = {"wide_screen_mode": True, "update_multi": True, "locales": ["zh_cn", "en_us"]}
    if summaryText:
        config["summary"] = {"content": summaryText[:120]}
    return {"config": config, "elements": elements}


def _BuildConfirmCard(confirmData: dict[str, str]) -> dict[str, object]:
    elements: list[dict[str, object]] = [
        {"tag": "div", "text": {"tag": "lark_md", "content": confirmData["operationDescription"]}}
    ]
    preview = confirmData.get("preview")
    if preview:
        elements.extend([{"tag": "hr"}, {"tag": "div", "text": {"tag": "lark_md", "content": f"**Preview:**\n{preview}"}}])
    elements.append({"tag": "hr"})
    actions: list[dict[str, object]] = [
        {
            "tag": "button",
            "text": {"tag": "plain_text", "content": "Confirm"},
            "type": "primary",
            "value": {"action": "confirm_write", "operation_id": confirmData["pendingOperationId"]},
        },
        {
            "tag": "button",
            "text": {"tag": "plain_text", "content": "Reject"},
            "type": "danger",
            "value": {"action": "reject_write", "operation_id": confirmData["pendingOperationId"]},
        },
    ]
    if not preview:
        actions.append(
            {
                "tag": "button",
                "text": {"tag": "plain_text", "content": "Preview"},
                "type": "default",
                "value": {"action": "preview_write", "operation_id": confirmData["pendingOperationId"]},
            }
        )
    elements.append({"tag": "action", "actions": actions})
    return {
        "config": {"wide_screen_mode": True, "update_multi": True},
        "header": {"title": {"tag": "plain_text", "content": "🔒 Confirmation Required"}, "template": "orange"},
        "elements": elements,
    }


def _BuildFooter(zhText: str, enText: str, isError: bool = False) -> list[dict[str, object]]:
    zhContent = f"<font color='red'>{zhText}</font>" if isError else zhText
    enContent = f"<font color='red'>{enText}</font>" if isError else enText
    return [
        {
            "tag": "markdown",
            "content": enContent,
            "i18n_content": {"zh_cn": zhContent, "en_us": enContent},
            "text_size": "notation",
        }
    ]


def _BuildStreamingReasoningPanel(
    content: str,
    withElementId: bool = True,
) -> dict[str, object]:
    """流式阶段思考折叠面板（默认折叠）。"""
    markdown: dict[str, object] = {
        "tag": "markdown",
        "content": content,
        "text_align": "left",
        "text_size": "notation",
        "margin": "0px 0px 0px 0px",
    }
    if withElementId:
        markdown["element_id"] = REASONING_ELEMENT_ID
    return {
        "tag": "collapsible_panel",
        "expanded": False,
        "header": {
            "title": {
                "tag": "markdown",
                "content": "💭 Thinking...",
                "i18n_content": {"zh_cn": "💭 思考中...", "en_us": "💭 Thinking..."},
            },
            "vertical_align": "center",
            "icon": {"tag": "standard_icon", "token": "down-small-ccm_outlined", "size": "16px 16px"},
            "icon_position": "follow_text",
            "icon_expanded_angle": -180,
        },
        "border": {"color": "grey", "corner_radius": "5px"},
        "vertical_spacing": "8px",
        "padding": "8px 8px 8px 8px",
        "elements": [markdown],
    }


def _BuildStreamingToolUsePendingPanel() -> dict[str, object]:
    """保留兼容；流式卡已不再挂载空工具 pending。"""
    return {
        "tag": "collapsible_panel",
        "expanded": False,
        "header": {
            "title": {
                "tag": "plain_text",
                "content": "🛠️ Tool use pending",
                "i18n_content": {"zh_cn": "🛠️ 等待工具执行", "en_us": "🛠️ Tool use pending"},
                "text_color": "grey",
                "text_size": "notation",
            },
            "vertical_align": "center",
            "icon": {"tag": "standard_icon", "token": "down-small-ccm_outlined", "color": "grey", "size": "16px 16px"},
            "icon_position": "right",
            "icon_expanded_angle": -180,
        },
        "border": {"color": "grey", "corner_radius": "5px"},
        "vertical_spacing": "4px",
        "padding": "8px 8px 8px 8px",
        "elements": [],
    }


def _BuildStreamingToolUseActivePanel(
    steps: list[ToolUseDisplayStep],
    elapsedMs: float | None,
    totalStepCount: int | None = None,
) -> dict[str, object]:
    count = totalStepCount if totalStepCount is not None else len(steps)
    enParts = ["Tool use"]
    zhParts = ["工具执行"]
    if count > 0:
        enParts.append(f"{count} step{'s' if count != 1 else ''}")
        zhParts.append(f"{count} 步")
    if elapsedMs and elapsedMs > 0:
        duration = FormatElapsed(elapsedMs)
        enParts.append(f"({duration})")
        zhParts.append(f"({duration})")
    stepElements: list[dict[str, object]] = []
    for step in steps:
        stepElements.extend(_BuildToolUseStepElements(step))
    return {
        "tag": "collapsible_panel",
        "expanded": True,
        "header": {
            "title": {
                "tag": "plain_text",
                "content": f"🛠️ {' · '.join(enParts)}",
                "i18n_content": {"zh_cn": f"🛠️ {' · '.join(zhParts)}", "en_us": f"🛠️ {' · '.join(enParts)}"},
                "text_color": "grey",
                "text_size": "notation",
            },
            "vertical_align": "center",
            "icon": {"tag": "standard_icon", "token": "down-small-ccm_outlined", "color": "grey", "size": "16px 16px"},
            "icon_position": "right",
            "icon_expanded_angle": -180,
        },
        "border": {"color": "grey", "corner_radius": "5px"},
        "vertical_spacing": "4px",
        "padding": "8px 8px 8px 8px",
        "elements": stepElements,
    }


def _BuildToolUsePanel(
    toolUseSteps: list[ToolUseDisplayStep],
    toolUseElapsedMs: float | None = None,
    titleSuffix: dict[str, str] | None = None,
    totalStepCount: int | None = None,
) -> dict[str, object]:
    duration = FormatToolUseDuration(toolUseElapsedMs) if toolUseElapsedMs else None
    zhTitleParts = [duration["zh"] if duration else "工具执行"]
    enTitleParts = [duration["en"] if duration else "Tool use"]
    if titleSuffix:
        zhTitleParts.append(titleSuffix["zh"])
        enTitleParts.append(titleSuffix["en"])
    stepElements = (
        [element for step in toolUseSteps for element in _BuildToolUseStepElements(step)]
        if toolUseSteps
        else [_BuildToolUsePlaceholder()]
    )
    return {
        "tag": "collapsible_panel",
        "expanded": False,
        "header": {
            "title": {
                "tag": "plain_text",
                "content": f"🛠️ {' · '.join(enTitleParts)}",
                "i18n_content": {"zh_cn": f"🛠️ {' · '.join(zhTitleParts)}", "en_us": f"🛠️ {' · '.join(enTitleParts)}"},
                "text_color": "grey",
                "text_size": "notation",
            },
            "vertical_align": "center",
            "icon": {"tag": "standard_icon", "token": "down-small-ccm_outlined", "color": "grey", "size": "16px 16px"},
            "icon_position": "right",
            "icon_expanded_angle": -180,
        },
        "border": {"color": "grey", "corner_radius": "5px"},
        "vertical_spacing": "4px",
        "padding": "8px 8px 8px 8px",
        "elements": stepElements,
    }


def _BuildToolUseStepElements(step: ToolUseDisplayStep) -> list[dict[str, object]]:
    """每条工具一行：标题 + 状态 + 详情合并为一行；输出块单独一行。"""
    elements: list[dict[str, object]] = [_BuildToolUseStepTitleElement(step)]
    outputElement = _BuildToolUseStepOutputElement(step)
    if outputElement:
        elements.append(outputElement)
    return elements


def _BuildToolUsePlaceholder(labels: dict[str, str] | None = None) -> dict[str, object]:
    zh = labels["zh"] if labels else "暂无工具步骤"
    en = labels["en"] if labels else EMPTY_TOOL_USE_PLACEHOLDER
    return {
        "tag": "div",
        "text": {
            "tag": "plain_text",
            "content": en,
            "i18n_content": {"zh_cn": zh, "en_us": en},
            "text_color": "grey",
            "text_size": "notation",
        },
    }


def _BuildToolUseStepTitleElement(step: ToolUseDisplayStep) -> dict[str, object]:
    """工具步骤标题行：工具名 · 状态 · 详情合并为一行。"""
    status = _FormatToolUseStepStatus(step.status)
    content = (
        f"**{_EscapeToolUseMarkdownText(step.title)}**"
        f" · <font color='{status['color']}'>{status['label']}</font>"
    )
    detail = (step.detail or "").strip()
    if detail:
        content += " · " + detail
    content = OptimizeMarkdownStyle(content, 1)
    return {
        "tag": "div",
        "icon": {"tag": "standard_icon", "token": step.iconToken, "color": "grey"},
        "text": {"tag": "lark_md", "content": content, "text_size": "notation"},
    }


def _BuildToolUseStepOutputElement(step: ToolUseDisplayStep) -> dict[str, object] | None:
    content = _BuildToolUseStepOutputMarkdown(step)
    if not content:
        return None
    return {
        "tag": "div",
        "margin": TOOL_USE_STEP_CONTENT_INDENT,
        "text": {"tag": "lark_md", "content": content, "text_size": "notation"},
    }


def _BuildToolUseStepOutputMarkdown(step: ToolUseDisplayStep) -> str | None:
    lines: list[str] = []
    if step.errorBlock:
        lines.extend(["**Error**", _FormatToolUseCodeBlock(step.errorBlock.content, step.errorBlock.language)])
    elif step.resultBlock:
        lines.extend(["**Result**", _FormatToolUseCodeBlock(step.resultBlock.content, step.resultBlock.language)])
    if not lines:
        return None
    return OptimizeMarkdownStyle("\n".join(lines), 1)


def _FormatToolUseStepStatus(status: ToolUseStepStatus) -> dict[str, str]:
    if status == "running":
        return {"label": "Running", "color": "turquoise"}
    if status == "error":
        return {"label": "Failed", "color": "red"}
    return {"label": "Succeeded", "color": "green"}


def _FormatToolUseCodeBlock(content: str, language: str) -> str:
    normalized = content.replace("\r\n", "\n").strip()
    longest = max((len(match.group(0)) for match in re.finditer(r"`+", normalized)), default=0)
    fence = "`" * max(3, longest + 1)
    return f"{fence}{language}\n{normalized}\n{fence}"


def _EscapeToolUseMarkdownText(value: str) -> str:
    return re.sub(r"([`*_{}\[\]<>])", r"\\\1", value.replace("\\", "\\\\"))


def _ExtractThinkingContent(text: str) -> str:
    scanRe = re.compile(r"<\s*(/?)\s*(?:think(?:ing)?|thought|antthinking)\s*>", re.IGNORECASE)
    result = ""
    lastIndex = 0
    inThinking = False
    for match in scanRe.finditer(text):
        idx = match.start()
        if inThinking:
            result += text[lastIndex:idx]
        inThinking = match.group(1) != "/"
        lastIndex = match.end()
    if inThinking:
        result += text[lastIndex:]
    return result.strip()


def _CleanReasoningPrefix(text: str) -> str:
    cleaned = re.sub(r"^Reasoning:\s*", "", text, flags=re.IGNORECASE)
    return "\n".join(re.sub(r"^_(.+)_$", r"\1", line) for line in cleaned.split("\n")).strip()
