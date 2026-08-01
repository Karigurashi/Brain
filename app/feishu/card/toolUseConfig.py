"""Tool-use 展示配置 —— mango 定死：开启工具面板、单行、不展开结果。"""

from __future__ import annotations

from app.feishu.card.replyDispatcherTypes import ToolUseDisplayConfig


def ResolveToolUseDisplayConfig(
    feishuCfg: object | None = None,
    sessionKey: str = "",
    body: str | None = None,
    verboseDefault: object | None = None,
) -> ToolUseDisplayConfig:
    # 签名保留兼容调用方；策略固定
    return ToolUseDisplayConfig(
        mode="on",
        showToolUse=True,
        showToolResultDetails=False,
        showFullPaths=False,
    )
