"""飞书事件处理器（对齐官方 event-handlers，去除话题/thread 逻辑）。"""

from __future__ import annotations

import json
from typing import Any, Optional

from app.channel import ChannelMessage, RouterComponent
from app.feishu.channel.interactiveDispatch import DispatchFeishuPluginInteractiveHandlerAsync
from app.feishu.channel.types import MonitorContext
from app.feishu.core.cardActionOperator import ResolveCardCallbackOperatorId
from app.feishu.messaging.converters.image import ConvertImageMessage, ExtractPostImageResources
from app.feishu.messaging.converters.interactive import ConvertInteractiveCard
from app.feishu.messaging.inbound import (
    DownloadResourcesAsync,
    ResourceDescriptor,
    SubstituteMediaPaths,
)
from common.cancellationToken import CancellationToken
from common.logger import Logger


def _IsEventOwnershipValid(ctx: MonitorContext, data: dict[str, Any]) -> bool:
    expected = ctx.config.appId
    if not expected:
        return True
    eventAppId = data.get("app_id")
    if eventAppId is None:
        header = data.get("header")
        if isinstance(header, dict):
            eventAppId = header.get("app_id")
    if eventAppId is None:
        return True
    if str(eventAppId) != expected:
        Logger.Warning(
            f"feishu[{ctx.accountId}]: event app_id mismatch, discarding "
            f"expected={expected} received={eventAppId}"
        )
        return False
    return True


def _DecodeInboundMessage(message: dict[str, Any]) -> tuple[str, list[ResourceDescriptor]]:
    """解析入站消息 → (文本, 待下载资源)，对齐官方 content converter。"""
    msgType = str(message.get("message_type") or message.get("msg_type") or "")
    contentRaw = message.get("content") or "{}"
    if isinstance(contentRaw, dict):
        content = contentRaw
    else:
        try:
            content = json.loads(str(contentRaw))
        except json.JSONDecodeError:
            return str(contentRaw), []

    if msgType in ("text", ""):
        return str(content.get("text") or "").strip(), []

    if msgType == "image":
        return ConvertImageMessage(content)

    if msgType == "post":
        text = _ExtractPostText(content)
        resources = ExtractPostImageResources(content)
        # 正文里补上未出现的图片 markdown，便于后续路径替换
        for res in resources:
            marker = f"![image]({res.fileKey})"
            if marker not in text:
                text = f"{text}\n{marker}".strip() if text else marker
        return text, resources

    if msgType == "interactive":
        raw = content if isinstance(content, str) else json.dumps(content, ensure_ascii=False)
        return ConvertInteractiveCard(raw).content or "", []

    return str(content.get("text") or json.dumps(content, ensure_ascii=False)), []


def _ExtractPostText(content: dict[str, Any]) -> str:
    for locale in ("zh_cn", "en_us", "ja_jp"):
        body = content.get(locale)
        if not isinstance(body, dict):
            continue
        lines: list[str] = []
        for row in body.get("content") or []:
            if not isinstance(row, list):
                continue
            parts: list[str] = []
            for item in row:
                if not isinstance(item, dict):
                    continue
                tag = item.get("tag")
                if tag in ("text", "md", "a"):
                    parts.append(str(item.get("text") or ""))
                elif tag == "at":
                    parts.append(f"@{item.get('user_name') or item.get('user_id') or ''}")
                elif tag in ("img", "image") and item.get("image_key"):
                    parts.append(f"![image]({item.get('image_key')})")
            if parts:
                lines.append("".join(parts))
        if lines:
            return "\n".join(lines)
    return ""


def _ResolveChatType(message: dict[str, Any]) -> str:
    chatType = str(message.get("chat_type") or "")
    if chatType in ("p2p", "group"):
        return chatType
    return "group" if str(message.get("chat_id") or "").startswith("oc_") else "p2p"


def _IsLikelyAbortText(text: str) -> bool:
    normalized = text.strip().lower()
    if not normalized:
        return False
    abortTokens = (
        "/stop",
        "stop",
        "停止",
        "取消",
        "停下",
        "abort",
        "cancel",
    )
    return normalized in abortTokens or normalized.startswith("/stop")


async def HandleMessageEventAsync(
    ctx: MonitorContext,
    data: dict[str, Any],
    cancellationToken: Optional[CancellationToken] = None,
) -> None:
    """处理 im.message.receive_v1（无话题 queue key / threadId）。"""
    if cancellationToken is not None:
        cancellationToken.ThrowIfCancellationRequested()
    if not _IsEventOwnershipValid(ctx, data):
        return

    event = data.get("event") if isinstance(data.get("event"), dict) else data
    if not isinstance(event, dict):
        Logger.Warning(
            f"feishu[{ctx.accountId}]: invalid message event payload "
            f"keys={list(data.keys()) if isinstance(data, dict) else type(data)}"
        )
        return
    message = event.get("message")
    sender = event.get("sender")
    if not isinstance(message, dict):
        Logger.Warning(
            f"feishu[{ctx.accountId}]: message event missing message field "
            f"eventKeys={list(event.keys())}"
        )
        return

    senderOpenId = ""
    if isinstance(sender, dict):
        senderId = sender.get("sender_id")
        if isinstance(senderId, dict):
            senderOpenId = str(senderId.get("open_id") or senderId.get("user_id") or "")

    if ctx.botOpenId and senderOpenId and senderOpenId == ctx.botOpenId:
        Logger.Info(
            f"feishu[{ctx.accountId}]: drop self-echo message "
            f"{message.get('message_id', 'unknown')}"
        )
        return

    chatId = str(message.get("chat_id") or "")
    messageId = str(message.get("message_id") or "")
    if not chatId:
        Logger.Warning(f"feishu[{ctx.accountId}]: message missing chat_id")
        return

    text, resources = _DecodeInboundMessage(message)

    # 对齐官方 resolveMedia：下载图片到本地，并把正文中的 image_key 替换为路径
    if resources and messageId:
        mediaList = await DownloadResourcesAsync(
            ctx.client,
            messageId,
            resources,
            cancellationToken=cancellationToken,
        )
        if mediaList:
            text = SubstituteMediaPaths(text, mediaList)
            Logger.Info(f"feishu[{ctx.accountId}]: media resolved count={len(mediaList)}")

    if not text.strip():
        Logger.Debug(f"feishu[{ctx.accountId}]: empty message content, skip")
        return

    chatType = _ResolveChatType(message)
    from app.feishu.component.card import CardComponent

    cardComponent = ctx.app.GetComponent(CardComponent)
    if messageId and cardComponent.IsDuplicateMessage(messageId):
        Logger.Info(f"feishu[{ctx.accountId}]: drop duplicate message {messageId}")
        return

    channel = ctx.app
    if _IsLikelyAbortText(text):
        try:
            if channel.Sdk.IsRunning(chatId):
                channel.Sdk.Cancel(chatId)
        except KeyError:
            pass
        await cardComponent.AbortActiveAsync(chatId)
        Logger.Info(f"feishu[{ctx.accountId}]: abort requested chatId={chatId}")
        return

    # 新消息：先取消同群旧 Agent，再换卡会话（对齐 openclaw queue/abort 隔离）
    try:
        if channel.Sdk.IsRunning(chatId):
            channel.Sdk.Cancel(chatId)
    except KeyError:
        pass
    await cardComponent.BeginReplyAsync(chatId, messageId, chatType)

    channelMessage = ChannelMessage(
        groupId=chatId,
        userId=senderOpenId or "unknown",
        content=text,
        userName=senderOpenId,
        groupName=chatId,
    )
    await ctx.app.GetComponent(RouterComponent).SendMessageAsync(channelMessage)


async def HandleCardActionEventAsync(
    ctx: MonitorContext,
    data: dict[str, Any],
    cancellationToken: Optional[CancellationToken] = None,
) -> dict[str, Any]:
    """处理 card.action.trigger。

    支持 inject_prompt（合成入站文本，不恢复 threadId）；
    其余交给 interactive dispatch。
    """
    if cancellationToken is not None:
        cancellationToken.ThrowIfCancellationRequested()
    if not _IsEventOwnershipValid(ctx, data):
        return {"toast": {"type": "error", "content": "invalid app"}}

    event = data.get("event") if isinstance(data.get("event"), dict) else data
    if not isinstance(event, dict):
        return {"toast": {"type": "error", "content": "invalid event"}}

    action = event.get("action") if isinstance(event.get("action"), dict) else {}
    value = action.get("value") if isinstance(action.get("value"), dict) else {}
    operatorId = ResolveCardCallbackOperatorId(
        event.get("operator") if isinstance(event.get("operator"), dict) else None
    )

    if str(value.get("action") or "") == "inject_prompt":
        prompt = str(value.get("prompt") or value.get("text") or "").strip()
        context = event.get("context") if isinstance(event.get("context"), dict) else {}
        chatId = str(context.get("open_chat_id") or context.get("chat_id") or "")
        if prompt and chatId:
            from app.feishu.component.card import CardComponent

            cardComponent = ctx.app.GetComponent(CardComponent)
            channel = ctx.app
            try:
                if channel.Sdk.IsRunning(chatId):
                    channel.Sdk.Cancel(chatId)
            except KeyError:
                pass
            await cardComponent.BeginReplyAsync(chatId, "", "group")
            msg = ChannelMessage(
                groupId=chatId,
                userId=operatorId or "unknown",
                content=prompt,
                userName=operatorId or "",
                groupName=chatId,
            )
            await ctx.app.GetComponent(RouterComponent).SendMessageAsync(msg)
            return {"toast": {"type": "info", "content": "已提交"}}

    try:
        return await DispatchFeishuPluginInteractiveHandlerAsync(data, cancellationToken)
    except Exception as exc:
        Logger.Error(f"feishu card action failed: {exc}")
        return {"toast": {"type": "error", "content": "处理失败"}}
