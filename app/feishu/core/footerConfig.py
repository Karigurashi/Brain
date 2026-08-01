"""飞书卡片 footer 配置解析。"""

from __future__ import annotations

from app.feishu.core.types import FeishuFooterConfig

DEFAULT_FOOTER_CONFIG: dict[str, bool] = {
    "status": False,
    "elapsed": True,
    "tokens": True,
    "cache": True,
    "context": False,
    "model": False,
}


def ResolveFooterConfig(cfg: FeishuFooterConfig | None = None) -> dict[str, bool]:
    if cfg is None:
        return dict(DEFAULT_FOOTER_CONFIG)
    return {
        "status": cfg.status if cfg.status is not None else DEFAULT_FOOTER_CONFIG["status"],
        "elapsed": cfg.elapsed if cfg.elapsed is not None else DEFAULT_FOOTER_CONFIG["elapsed"],
        "tokens": cfg.tokens if cfg.tokens is not None else DEFAULT_FOOTER_CONFIG["tokens"],
        "cache": cfg.cache if cfg.cache is not None else DEFAULT_FOOTER_CONFIG["cache"],
        "context": cfg.context if cfg.context is not None else DEFAULT_FOOTER_CONFIG["context"],
        "model": cfg.model if cfg.model is not None else DEFAULT_FOOTER_CONFIG["model"],
    }
