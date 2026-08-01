"""入站交互卡片转换。"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from enum import IntEnum
from typing import Any, Callable, Optional

from app.feishu.messaging.converters.interactive.cardUtils import (
    EscapeAttr,
    FormatMillisecondsToISO8601,
    NormalizeTimeFormat,
)

Obj = dict[str, Any]


class EConvertMode(IntEnum):
    CONCISE = 0
    DETAILED = 1


@dataclass
class RawCardContent:
    json_card: str
    json_attachment: str | None = None
    card_schema: int | None = None


@dataclass
class ConvertCardResult:
    content: str
    schema: int


@dataclass
class TextStyle:
    bold: bool = False
    italic: bool = False
    strikethrough: bool = False


EMOJI_MAP = {
    "OK": "👌",
    "THUMBSUP": "👍",
    "SMILE": "😊",
    "HEART": "❤️",
    "CLAP": "👏",
    "FIRE": "🔥",
    "PARTY": "🎉",
    "THINK": "🤔",
}

CHART_TYPE_NAMES = {
    "bar": "柱状图",
    "line": "折线图",
    "pie": "饼图",
    "area": "面积图",
    "radar": "雷达图",
    "scatter": "散点图",
}


def SafeParse(raw: str) -> Obj | None:
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


class CardConverter:
    def __init__(self, mode: EConvertMode = EConvertMode.CONCISE) -> None:
        self._mode = mode
        self._attachment: Obj | None = None

    def Convert(self, inputData: RawCardContent) -> ConvertCardResult:
        card = SafeParse(inputData.json_card)
        if card is None:
            return ConvertCardResult(content="<card>\n[无法解析卡片内容]\n</card>", schema=0)
        if inputData.json_attachment:
            self._attachment = SafeParse(inputData.json_attachment)
        schema = inputData.card_schema or 0
        if schema == 0:
            schemaValue = card.get("schema")
            schema = int(schemaValue) if isinstance(schemaValue, int) else 1
        header = card.get("header")
        title = self._ExtractHeaderTitle(header, schema) if isinstance(header, dict) else ""
        body = self._ExtractBody(card)
        bodyContent = self.ConvertBody(body, schema) if body else ""
        output = f'<card title="{EscapeAttr(title)}">\n' if title else "<card>\n"
        if bodyContent:
            output += bodyContent + "\n"
        output += "</card>"
        return ConvertCardResult(content=output, schema=schema)

    def ConvertBody(self, body: Obj, _schema: int) -> str:
        elements = None
        prop = body.get("property")
        if isinstance(prop, dict):
            candidate = prop.get("elements")
            if isinstance(candidate, list) and candidate:
                elements = candidate
        if elements is None:
            candidate = body.get("elements")
            if isinstance(candidate, list):
                elements = candidate
        if not elements:
            return ""
        return self.ConvertElements(elements, 0)

    def ConvertElements(self, elements: list[Any], depth: int) -> str:
        results: list[str] = []
        for elem in elements:
            if not isinstance(elem, dict):
                continue
            converted = self.ConvertElement(elem, depth)
            if converted:
                results.append(converted)
        return "\n".join(results)

    def ConvertElement(self, elem: Obj, depth: int) -> str:
        tag = str(elem.get("tag") or "")
        elementId = str(elem.get("id") or "")
        prop = self._ExtractProperty(elem)
        converter = _ELEMENT_CONVERTERS.get(tag)
        if converter:
            return converter(self, elem, prop, elementId, depth)
        return self.ConvertUnknown(prop, tag)

    def ConvertUnknown(self, prop: Obj | None, tag: str) -> str:
        if prop is None:
            return f"[未知内容](tag:{tag})" if self._mode == EConvertMode.DETAILED else "[未知内容]"
        for key in ("content", "text", "title", "label", "placeholder"):
            if prop.get(key) is not None:
                text = self.ExtractTextContent(prop[key])
                if text:
                    return text
        elements = prop.get("elements")
        if isinstance(elements, list) and elements:
            return self.ConvertElements(elements, 0)
        return f"[未知内容](tag:{tag})" if self._mode == EConvertMode.DETAILED else "[未知内容]"

    def ExtractTextContent(self, textElem: Any) -> str:
        if textElem is None:
            return ""
        if isinstance(textElem, str):
            return textElem
        if isinstance(textElem, dict):
            if isinstance(textElem.get("property"), dict):
                return self._ExtractTextFromProperty(textElem["property"])
            return self._ExtractTextFromProperty(textElem)
        return ""

    def ConvertPlainText(self, prop: Obj) -> str:
        content = prop.get("content")
        if not isinstance(content, str) or not content:
            return ""
        return self._ApplyTextStyle(content, self._ExtractTextStyle(prop))

    def ConvertMarkdown(self, prop: Obj) -> str:
        elements = prop.get("elements")
        if isinstance(elements, list) and elements:
            return self.ConvertMarkdownElements(elements)
        content = prop.get("content")
        return content if isinstance(content, str) else ""

    def ConvertMarkdownElements(self, elements: list[Any]) -> str:
        return "".join(self.ConvertElement(elem, 0) for elem in elements if isinstance(elem, dict))

    def ConvertDiv(self, prop: Obj, _elementId: str) -> str:
        results: list[str] = []
        textElem = prop.get("text")
        if isinstance(textElem, dict):
            text = self.ConvertElement(textElem, 0)
            if text:
                results.append(text)
        fields = prop.get("fields")
        if isinstance(fields, list):
            fieldTexts = []
            for field in fields:
                if isinstance(field, dict) and isinstance(field.get("text"), dict):
                    fieldText = self.ConvertElement(field["text"], 0)
                    if fieldText:
                        fieldTexts.append(fieldText)
            if fieldTexts:
                results.append("\n".join(fieldTexts))
        extraElem = prop.get("extra")
        if isinstance(extraElem, dict):
            extra = self.ConvertElement(extraElem, 0)
            if extra:
                results.append(extra)
        return "\n".join(results)

    def ConvertNote(self, prop: Obj) -> str:
        elements = prop.get("elements")
        if not isinstance(elements, list):
            return ""
        texts = [self.ConvertElement(elem, 0) for elem in elements if isinstance(elem, dict)]
        texts = [text for text in texts if text]
        return f"📝 {' '.join(texts)}" if texts else ""

    def ConvertHr(self, _prop: Obj, _elementId: str) -> str:
        return "---"

    def ConvertColumnSet(self, prop: Obj, depth: int) -> str:
        columns = prop.get("columns")
        if not isinstance(columns, list):
            return ""
        results = [self.ConvertElement(col, depth + 1) for col in columns if isinstance(col, dict)]
        return "\n\n".join(text for text in results if text)

    def ConvertColumn(self, prop: Obj, depth: int) -> str:
        elements = prop.get("elements")
        if not isinstance(elements, list):
            return ""
        return self.ConvertElements(elements, depth)

    def ConvertButton(self, prop: Obj, _elementId: str) -> str:
        textElem = prop.get("text")
        buttonText = self.ExtractTextContent(textElem) if textElem else "按钮"
        actions = prop.get("actions")
        if isinstance(actions, list):
            for action in actions:
                if isinstance(action, dict) and action.get("type") == "open_url":
                    actionData = action.get("action")
                    if isinstance(actionData, dict) and actionData.get("url"):
                        return f"[{buttonText}]({actionData['url']})"
        if prop.get("disabled") is True:
            return f"[{buttonText} ✗]"
        return f"[{buttonText}]"

    def ConvertActions(self, prop: Obj) -> str:
        actions = prop.get("actions")
        if not isinstance(actions, list):
            return ""
        results = [self.ConvertElement(action, 0) for action in actions if isinstance(action, dict)]
        return " ".join(text for text in results if text)

    def ConvertImage(self, prop: Obj, _elementId: str) -> str:
        alt = "图片"
        for key in ("alt", "title"):
            elem = prop.get(key)
            if isinstance(elem, dict):
                altText = self.ExtractTextContent(elem)
                if altText:
                    alt = altText
        return f"🖼️ {alt}"

    def ConvertCollapsiblePanel(self, prop: Obj, _elementId: str) -> str:
        expanded = prop.get("expanded") is True
        title = "详情"
        header = prop.get("header")
        if isinstance(header, dict) and header.get("title") is not None:
            titleText = self.ExtractTextContent(header["title"])
            if titleText:
                title = titleText
        if expanded or self._mode == EConvertMode.DETAILED:
            output = f"▼ {title}\n"
            elements = prop.get("elements")
            if isinstance(elements, list):
                content = self.ConvertElements(elements, 1)
                for line in content.split("\n"):
                    if line:
                        output += f"    {line}\n"
            output += "▲"
            return output
        return f"▶ {title}"

    def ConvertTable(self, prop: Obj) -> str:
        columns = prop.get("columns")
        if not isinstance(columns, list) or not columns:
            return ""
        rows = prop.get("rows") if isinstance(prop.get("rows"), list) else []
        colNames: list[str] = []
        colKeys: list[str] = []
        for col in columns:
            if not isinstance(col, dict):
                continue
            displayName = str(col.get("displayName") or col.get("name") or "")
            colNames.append(displayName)
            colKeys.append(str(col.get("name") or ""))
        lines = ["| " + " | ".join(colNames) + " |", "|" + "|".join(["------"] * len(colNames)) + "|"]
        for row in rows:
            if not isinstance(row, dict):
                continue
            cells = []
            for key in colKeys:
                cellData = row.get(key)
                cellValue = ""
                if isinstance(cellData, dict) and cellData.get("data") is not None:
                    cellValue = self._ExtractTableCellValue(cellData["data"])
                cells.append(cellValue)
            lines.append("| " + " | ".join(cells) + " |")
        return "\n".join(lines)

    def ConvertAt(self, prop: Obj) -> str:
        userId = str(prop.get("userID") or "")
        if not userId:
            return ""
        userName = ""
        if self._attachment and isinstance(self._attachment.get("at_users"), dict):
            userInfo = self._attachment["at_users"].get(userId)
            if isinstance(userInfo, dict) and isinstance(userInfo.get("content"), str):
                userName = userInfo["content"]
        if userName:
            return f"@{userName}"
        return f"@{userId}"

    def _ExtractBody(self, card: Obj) -> Obj | None:
        body = card.get("body")
        return body if isinstance(body, dict) else None

    def _ExtractHeaderTitle(self, header: Obj, _schema: int) -> str:
        prop = header.get("property")
        if isinstance(prop, dict) and prop.get("title") is not None:
            return self.ExtractTextContent(prop["title"])
        if header.get("title") is not None:
            return self.ExtractTextContent(header["title"])
        return ""

    def _ExtractProperty(self, elem: Obj) -> Obj:
        prop = elem.get("property")
        return prop if isinstance(prop, dict) else elem

    def _ExtractTextFromProperty(self, prop: Obj) -> str:
        i18n = prop.get("i18nContent") or prop.get("i18n_content")
        if isinstance(i18n, dict):
            for lang in ("zh_cn", "en_us", "ja_jp"):
                value = i18n.get(lang)
                if isinstance(value, str) and value:
                    return value
        content = prop.get("content")
        if isinstance(content, str):
            return content
        elements = prop.get("elements")
        if isinstance(elements, list):
            return "".join(self.ExtractTextContent(elem) for elem in elements)
        text = prop.get("text")
        return text if isinstance(text, str) else ""

    def _ExtractTextStyle(self, prop: Obj) -> TextStyle:
        style = TextStyle()
        textStyle = prop.get("textStyle")
        if not isinstance(textStyle, dict):
            return style
        attrs = textStyle.get("attributes")
        if isinstance(attrs, list):
            for attr in attrs:
                if attr == "bold":
                    style.bold = True
                elif attr == "italic":
                    style.italic = True
                elif attr == "strikethrough":
                    style.strikethrough = True
        return style

    def _ApplyTextStyle(self, content: str, style: TextStyle) -> str:
        if not content:
            return content
        if style.strikethrough:
            content = f"~~{content}~~"
        if style.italic:
            content = f"*{content}*"
        if style.bold:
            content = f"**{content}**"
        return content

    def _ExtractTableCellValue(self, data: Any) -> str:
        if isinstance(data, str):
            return data
        if isinstance(data, (int, float)):
            return f"{data:.2f}"
        if isinstance(data, list):
            texts = []
            for item in data:
                if isinstance(item, dict) and isinstance(item.get("text"), str):
                    texts.append(f"「{item['text']}」")
            return " ".join(texts)
        if isinstance(data, dict):
            return self.ExtractTextContent(data)
        return ""


ElementConverter = Callable[["CardConverter", Obj, Obj, str, int], str]


def _Register(tag: str, fn: ElementConverter) -> None:
    _ELEMENT_CONVERTERS[tag] = fn


_ELEMENT_CONVERTERS: dict[str, ElementConverter] = {}
_Register("plain_text", lambda c, _e, p, _i, _d: c.ConvertPlainText(p))
_Register("markdown", lambda c, _e, p, _i, _d: c.ConvertMarkdown(p))
_Register("markdown_v1", lambda c, e, p, _i, _d: c.ConvertMarkdown(p) or c.ConvertElement(e.get("fallback", {}), 0))
_Register("text", lambda c, _e, p, _i, _d: c.ConvertPlainText(p))
_Register("div", lambda c, _e, p, i, _d: c.ConvertDiv(p, i))
_Register("note", lambda c, _e, p, _i, _d: c.ConvertNote(p))
_Register("hr", lambda c, _e, _p, i, _d: c.ConvertHr(_p, i))
_Register("br", lambda _c, _e, _p, _i, _d: "\n")
_Register("column_set", lambda c, _e, p, _i, d: c.ConvertColumnSet(p, d))
_Register("column", lambda c, _e, p, _i, d: c.ConvertColumn(p, d))
_Register("button", lambda c, _e, p, i, _d: c.ConvertButton(p, i))
_Register("actions", lambda c, _e, p, _i, _d: c.ConvertActions(p))
_Register("action", lambda c, _e, p, _i, _d: c.ConvertActions(p))
_Register("img", lambda c, _e, p, i, _d: c.ConvertImage(p, i))
_Register("image", lambda c, _e, p, i, _d: c.ConvertImage(p, i))
_Register("table", lambda c, _e, p, _i, _d: c.ConvertTable(p))
_Register("collapsible_panel", lambda c, _e, p, i, _d: c.ConvertCollapsiblePanel(p, i))
_Register("at", lambda c, _e, p, _i, _d: c.ConvertAt(p))
_Register("at_all", lambda _c, _e, _p, _i, _d: "@所有人")
_Register("card_header", lambda _c, _e, _p, _i, _d: "")
_Register("custom_icon", lambda _c, _e, _p, _i, _d: "")
_Register("standard_icon", lambda _c, _e, _p, _i, _d: "")


def ConvertInteractiveCard(
    jsonCard: str,
    jsonAttachment: str | None = None,
    cardSchema: int | None = None,
    mode: EConvertMode = EConvertMode.CONCISE,
) -> ConvertCardResult:
    converter = CardConverter(mode)
    return converter.Convert(
        RawCardContent(json_card=jsonCard, json_attachment=jsonAttachment, card_schema=cardSchema)
    )
