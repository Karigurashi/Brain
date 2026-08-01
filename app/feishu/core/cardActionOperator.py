"""卡片回调操作者身份提取。"""

from __future__ import annotations

from typing import Optional

from app.feishu.core.types import CardCallbackOperator


def ResolveCardCallbackOperatorId(
    operator: Optional[CardCallbackOperator | dict],
) -> Optional[str]:
    if operator is None:
        return None
    if isinstance(operator, dict):
        openId = operator.get("open_id")
        userId = operator.get("user_id")
        if isinstance(openId, str) and openId:
            return openId
        if isinstance(userId, str) and userId:
            return userId
        return None
    if operator.open_id:
        return operator.open_id
    return operator.user_id
