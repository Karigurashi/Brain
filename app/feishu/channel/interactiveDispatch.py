"""飞书交互卡片回调分发（对齐官方 interactive-dispatch，无话题语义）。"""

from __future__ import annotations

from typing import Any, Optional

from app.feishu.core.cardActionOperator import ResolveCardCallbackOperatorId
from common.cancellationToken import CancellationToken
from common.logger import Logger


async def DispatchFeishuPluginInteractiveHandlerAsync(
    data: dict[str, Any],
    cancellationToken: Optional[CancellationToken] = None,
) -> dict[str, Any]:
    """处理插件侧 interactive 回调。

    当前返回 toast 占位；业务插件可在此扩展。
    不恢复 threadId / replyInThread（话题功能已去除）。
    """
    if cancellationToken is not None:
        cancellationToken.ThrowIfCancellationRequested()

    event = data.get("event") if isinstance(data.get("event"), dict) else data
    action = event.get("action") if isinstance(event, dict) else None
    operator = event.get("operator") if isinstance(event, dict) else None
    operatorId = ResolveCardCallbackOperatorId(operator if isinstance(operator, dict) else None)
    actionName = ""
    if isinstance(action, dict):
        value = action.get("value")
        if isinstance(value, dict):
            actionName = str(value.get("action") or "")
        else:
            actionName = str(action.get("tag") or "")

    Logger.Info(
        f"feishu interactive dispatch: operator={operatorId}, action={actionName or 'unknown'}"
    )
    return {
        "toast": {
            "type": "info",
            "content": "已收到操作" if not actionName else f"已处理: {actionName}",
        }
    }
