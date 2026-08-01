"""飞书 / Lark REST 客户端封装。"""

from __future__ import annotations

import json
import re
import time
from typing import Any, Optional
from urllib.parse import unquote

import httpx

from app.feishu.core.apiError import AssertLarkOk
from app.feishu.core.types import FeishuCredentials, FeishuProbeResult, LarkBrand
from common.cancellationToken import CancellationToken
from common.logger import Logger

_DOMAIN_MAP: dict[str, str] = {
    "feishu": "https://open.feishu.cn",
    "lark": "https://open.larksuite.com",
}

_clientCache: dict[str, "LarkClient"] = {}


def _ResolveDomain(brand: LarkBrand) -> str:
    if brand in _DOMAIN_MAP:
        return _DOMAIN_MAP[brand]
    return str(brand).rstrip("/")


class LarkClient:
    def __init__(self, credentials: FeishuCredentials) -> None:
        self._credentials = credentials
        self._domain = _ResolveDomain(credentials.brand)
        self._tenantAccessToken: Optional[str] = None
        self._tokenExpiresAt = 0.0
        self._http = httpx.AsyncClient(timeout=30.0)

    @property
    def AccountId(self) -> str:
        return self._credentials.accountId

    @classmethod
    def FromCredentials(cls, credentials: FeishuCredentials) -> "LarkClient":
        cacheKey = credentials.accountId or "default"
        existing = _clientCache.get(cacheKey)
        if (
            existing is not None
            and existing._credentials.appId == credentials.appId
            and existing._credentials.appSecret == credentials.appSecret
        ):
            return existing
        instance = cls(credentials)
        _clientCache[cacheKey] = instance
        return instance

    async def CloseAsync(self, cancellationToken: Optional[CancellationToken] = None) -> None:
        if cancellationToken is not None:
            cancellationToken.ThrowIfCancellationRequested()
        await self._http.aclose()

    async def _EnsureTokenAsync(self, cancellationToken: Optional[CancellationToken] = None) -> str:
        if cancellationToken is not None:
            cancellationToken.ThrowIfCancellationRequested()
        now = time.time()
        if self._tenantAccessToken and now < self._tokenExpiresAt - 60:
            return self._tenantAccessToken
        url = f"{self._domain}/open-apis/auth/v3/tenant_access_token/internal"
        response = await self._http.post(
            url,
            json={"app_id": self._credentials.appId, "app_secret": self._credentials.appSecret},
        )
        data = response.json()
        AssertLarkOk(data)
        token = str(data.get("tenant_access_token", ""))
        expire = int(data.get("expire", 7200))
        self._tenantAccessToken = token
        self._tokenExpiresAt = now + expire
        return token

    async def _RequestAsync(
        self,
        method: str,
        path: str,
        cancellationToken: Optional[CancellationToken] = None,
        params: Optional[dict[str, str]] = None,
        jsonBody: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        if cancellationToken is not None:
            cancellationToken.ThrowIfCancellationRequested()
        token = await self._EnsureTokenAsync(cancellationToken)
        url = f"{self._domain}{path}"
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json; charset=utf-8"}
        response = await self._http.request(method, url, params=params, json=jsonBody, headers=headers)
        data = response.json()
        if not isinstance(data, dict):
            raise RuntimeError(f"Unexpected Feishu response: {response.text[:200]}")
        AssertLarkOk(data, api=f"{method} {path}")
        return data

    async def CreateCardEntityAsync(
        self,
        card: dict[str, Any],
        cancellationToken: Optional[CancellationToken] = None,
    ) -> Optional[str]:
        data = await self._RequestAsync(
            "POST",
            "/open-apis/cardkit/v1/cards",
            cancellationToken=cancellationToken,
            jsonBody={"type": "card_json", "data": json.dumps(card, ensure_ascii=False)},
        )
        payload = data.get("data")
        if isinstance(payload, dict):
            cardId = payload.get("card_id")
            if isinstance(cardId, str) and cardId:
                return cardId
        return None

    async def StreamCardContentAsync(
        self,
        cardId: str,
        elementId: str,
        content: str,
        sequence: int,
        cancellationToken: Optional[CancellationToken] = None,
    ) -> None:
        await self._RequestAsync(
            "PUT",
            f"/open-apis/cardkit/v1/cards/{cardId}/elements/{elementId}/content",
            cancellationToken=cancellationToken,
            jsonBody={"content": content, "sequence": sequence},
        )

    async def UpdateCardKitCardAsync(
        self,
        cardId: str,
        card: dict[str, Any],
        sequence: int,
        cancellationToken: Optional[CancellationToken] = None,
    ) -> None:
        await self._RequestAsync(
            "PUT",
            f"/open-apis/cardkit/v1/cards/{cardId}",
            cancellationToken=cancellationToken,
            jsonBody={
                "card": {"type": "card_json", "data": json.dumps(card, ensure_ascii=False)},
                "sequence": sequence,
            },
        )

    async def SetCardStreamingModeAsync(
        self,
        cardId: str,
        streamingMode: bool,
        sequence: int,
        cancellationToken: Optional[CancellationToken] = None,
    ) -> None:
        await self._RequestAsync(
            "PATCH",
            f"/open-apis/cardkit/v1/cards/{cardId}/settings",
            cancellationToken=cancellationToken,
            jsonBody={
                "settings": json.dumps({"streaming_mode": streamingMode}),
                "sequence": sequence,
            },
        )

    async def SendCardByCardIdAsync(
        self,
        to: str,
        cardId: str,
        replyToMessageId: Optional[str] = None,
        cancellationToken: Optional[CancellationToken] = None,
    ) -> dict[str, str]:
        from app.feishu.core.targets import NormalizeFeishuTarget, NormalizeMessageId, ResolveReceiveIdType

        contentPayload = json.dumps({"type": "card", "data": {"card_id": cardId}}, ensure_ascii=False)
        if replyToMessageId:
            normalizedId = NormalizeMessageId(replyToMessageId)
            data = await self._RequestAsync(
                "POST",
                f"/open-apis/im/v1/messages/{normalizedId}/reply",
                cancellationToken=cancellationToken,
                jsonBody={"content": contentPayload, "msg_type": "interactive"},
            )
            payload = data.get("data") if isinstance(data.get("data"), dict) else {}
            return {
                "messageId": str(payload.get("message_id", "")),
                "chatId": str(payload.get("chat_id", "")),
            }

        target = NormalizeFeishuTarget(to)
        if not target:
            raise ValueError(f'[feishu-send] Invalid target: "{to}"')
        receiveIdType = ResolveReceiveIdType(target)
        data = await self._RequestAsync(
            "POST",
            "/open-apis/im/v1/messages",
            cancellationToken=cancellationToken,
            params={"receive_id_type": receiveIdType},
            jsonBody={"receive_id": target, "msg_type": "interactive", "content": contentPayload},
        )
        payload = data.get("data") if isinstance(data.get("data"), dict) else {}
        return {
            "messageId": str(payload.get("message_id", "")),
            "chatId": str(payload.get("chat_id", "")),
        }

    async def SendInteractiveMessageAsync(
        self,
        to: str,
        card: dict[str, Any],
        replyToMessageId: Optional[str] = None,
        cancellationToken: Optional[CancellationToken] = None,
    ) -> dict[str, str]:
        from app.feishu.core.targets import NormalizeFeishuTarget, NormalizeMessageId, ResolveReceiveIdType

        contentPayload = json.dumps(card, ensure_ascii=False)
        if replyToMessageId:
            normalizedId = NormalizeMessageId(replyToMessageId)
            data = await self._RequestAsync(
                "POST",
                f"/open-apis/im/v1/messages/{normalizedId}/reply",
                cancellationToken=cancellationToken,
                jsonBody={"content": contentPayload, "msg_type": "interactive"},
            )
            payload = data.get("data") if isinstance(data.get("data"), dict) else {}
            return {
                "messageId": str(payload.get("message_id", "")),
                "chatId": str(payload.get("chat_id", "")),
            }

        target = NormalizeFeishuTarget(to)
        if not target:
            raise ValueError(f'[feishu-send] Invalid target: "{to}"')
        receiveIdType = ResolveReceiveIdType(target)
        data = await self._RequestAsync(
            "POST",
            "/open-apis/im/v1/messages",
            cancellationToken=cancellationToken,
            params={"receive_id_type": receiveIdType},
            jsonBody={"receive_id": target, "msg_type": "interactive", "content": contentPayload},
        )
        payload = data.get("data") if isinstance(data.get("data"), dict) else {}
        return {
            "messageId": str(payload.get("message_id", "")),
            "chatId": str(payload.get("chat_id", "")),
        }

    async def PatchInteractiveMessageAsync(
        self,
        messageId: str,
        card: dict[str, Any],
        cancellationToken: Optional[CancellationToken] = None,
    ) -> None:
        data = await self._RequestAsync(
            "PATCH",
            f"/open-apis/im/v1/messages/{messageId}",
            cancellationToken=cancellationToken,
            jsonBody={"content": json.dumps(card, ensure_ascii=False)},
        )

    async def SendPostMessageAsync(
        self,
        to: str,
        text: str,
        replyToMessageId: Optional[str] = None,
        cancellationToken: Optional[CancellationToken] = None,
    ) -> dict[str, str]:
        from app.feishu.card.markdownStyle import OptimizeMarkdownStyle
        from app.feishu.core.targets import NormalizeFeishuTarget, NormalizeMessageId, ResolveReceiveIdType

        messageText = OptimizeMarkdownStyle(text, 1)
        contentPayload = json.dumps(
            {"zh_cn": {"content": [[{"tag": "md", "text": messageText}]]}},
            ensure_ascii=False,
        )
        if replyToMessageId:
            normalizedId = NormalizeMessageId(replyToMessageId)
            data = await self._RequestAsync(
                "POST",
                f"/open-apis/im/v1/messages/{normalizedId}/reply",
                cancellationToken=cancellationToken,
                jsonBody={"content": contentPayload, "msg_type": "post"},
            )
            payload = data.get("data") if isinstance(data.get("data"), dict) else {}
            return {
                "messageId": str(payload.get("message_id", "")),
                "chatId": str(payload.get("chat_id", "")),
            }

        target = NormalizeFeishuTarget(to)
        if not target:
            raise ValueError(f'[feishu-send] Invalid target: "{to}"')
        receiveIdType = ResolveReceiveIdType(target)
        data = await self._RequestAsync(
            "POST",
            "/open-apis/im/v1/messages",
            cancellationToken=cancellationToken,
            params={"receive_id_type": receiveIdType},
            jsonBody={"receive_id": target, "msg_type": "post", "content": contentPayload},
        )
        payload = data.get("data") if isinstance(data.get("data"), dict) else {}
        return {
            "messageId": str(payload.get("message_id", "")),
            "chatId": str(payload.get("chat_id", "")),
        }

    async def DownloadMessageResourceAsync(
        self,
        messageId: str,
        fileKey: str,
        resourceType: str = "image",
        cancellationToken: Optional[CancellationToken] = None,
    ) -> tuple[bytes, str, Optional[str]]:
        """下载消息中的图片/文件资源。

        对齐官方 downloadMessageResourceFeishu：
        GET /open-apis/im/v1/messages/:message_id/resources/:file_key

        Args:
            messageId: 消息 ID（om_xxx）。
            fileKey: image_key / file_key。
            resourceType: ``image`` 或 ``file``。

        Returns:
            (buffer, contentType, fileName)
        """
        if cancellationToken is not None:
            cancellationToken.ThrowIfCancellationRequested()
        token = await self._EnsureTokenAsync(cancellationToken)
        path = f"/open-apis/im/v1/messages/{messageId}/resources/{fileKey}"
        url = f"{self._domain}{path}"
        headers = {"Authorization": f"Bearer {token}"}
        response = await self._http.get(
            url,
            params={"type": resourceType},
            headers=headers,
        )
        contentType = str(response.headers.get("content-type") or "")
        # 错误时飞书返回 JSON
        if "application/json" in contentType.lower():
            data = response.json()
            if isinstance(data, dict):
                AssertLarkOk(data, api=f"GET {path}")
            raise RuntimeError(f"Unexpected JSON when downloading resource: {response.text[:200]}")
        if response.status_code >= 400:
            raise RuntimeError(
                f"Download message resource failed status={response.status_code}: {response.text[:200]}"
            )

        fileName: Optional[str] = None
        disposition = response.headers.get("content-disposition") or response.headers.get(
            "Content-Disposition"
        )
        if disposition:
            match = re.search(r"filename\*?=(?:UTF-8''|\"?)([^\";\n]+)", disposition, re.IGNORECASE)
            if match:
                fileName = unquote(match.group(1).strip().strip('"'))

        return response.content, contentType, fileName

    async def ProbeAsync(
        self,
        cancellationToken: Optional[CancellationToken] = None,
    ) -> FeishuProbeResult:
        if not self._credentials.appId or not self._credentials.appSecret:
            return FeishuProbeResult(ok=False, error="missing credentials (appId, appSecret)")
        try:
            await self._EnsureTokenAsync(cancellationToken)
            data = await self._RequestAsync(
                "GET",
                "/open-apis/bot/v3/info",
                cancellationToken=cancellationToken,
            )
            bot = data.get("bot") if isinstance(data.get("bot"), dict) else {}
            return FeishuProbeResult(
                ok=True,
                appId=self._credentials.appId,
                botName=str(bot.get("app_name") or "") or None,
                botOpenId=str(bot.get("open_id") or "") or None,
            )
        except Exception as err:
            Logger.Warning(f"LarkClient probe failed: {err}")
            return FeishuProbeResult(ok=False, appId=self._credentials.appId, error=str(err))

    # ---- Reaction API ----

    async def AddReactionAsync(
        self,
        messageId: str,
        emojiType: str,
        cancellationToken: Optional[CancellationToken] = None,
    ) -> str | None:
        """给消息添加表情反应，返回 reaction_id。

        POST /open-apis/im/v1/messages/{message_id}/reactions
        """
        data = await self._RequestAsync(
            "POST",
            f"/open-apis/im/v1/messages/{messageId}/reactions",
            cancellationToken=cancellationToken,
            jsonBody={"reaction_type": {"emoji_type": emojiType}},
        )
        payload = data.get("data") if isinstance(data.get("data"), dict) else {}
        reactionId = payload.get("reaction_id")
        return str(reactionId) if reactionId else None

    async def DeleteReactionAsync(
        self,
        messageId: str,
        reactionId: str,
        cancellationToken: Optional[CancellationToken] = None,
    ) -> None:
        """删除消息上的表情反应。

        DELETE /open-apis/im/v1/messages/{message_id}/reactions/{reaction_id}
        """
        await self._RequestAsync(
            "DELETE",
            f"/open-apis/im/v1/messages/{messageId}/reactions/{reactionId}",
            cancellationToken=cancellationToken,
        )

    async def ListReactionsAsync(
        self,
        messageId: str,
        emojiType: Optional[str] = None,
        pageToken: Optional[str] = None,
        pageSize: int = 50,
        cancellationToken: Optional[CancellationToken] = None,
    ) -> dict[str, Any]:
        """获取消息上的表情反应列表（分页）。

        GET /open-apis/im/v1/messages/{message_id}/reactions

        Returns:
            {"items": [...], "has_more": bool, "page_token": str | None}
        """
        params: dict[str, str] = {"page_size": str(pageSize)}
        if emojiType:
            params["reaction_type"] = emojiType
        if pageToken:
            params["page_token"] = pageToken
        data = await self._RequestAsync(
            "GET",
            f"/open-apis/im/v1/messages/{messageId}/reactions",
            cancellationToken=cancellationToken,
            params=params,
        )
        payload = data.get("data") if isinstance(data.get("data"), dict) else {}
        return {
            "items": payload.get("items") or [],
            "has_more": payload.get("has_more") is True,
            "page_token": payload.get("page_token") or None,
        }
