"""统一日志管理器，静态类，极简调用。

使用方式::
    Logger.Info("模型调用成功")
    Logger.Error("请求超时")
    Logger.Warning("重试中")
    Logger.Debug("raw response: ...")
"""

from __future__ import annotations

import logging
import sys


# ---- ANSI 颜色 ----

_RESET = "\033[0m"
_RED = "\033[31m"
_YELLOW = "\033[33m"

_LEVEL_COLORS = {
    logging.ERROR: _RED,
    logging.WARNING: _YELLOW,
}


class _ColoredFormatter(logging.Formatter):
    """按日志级别染色：ERROR 红色，WARNING 黄色。"""

    def format(self, record: logging.LogRecord) -> str:
        line = super().format(record)
        color = _LEVEL_COLORS.get(record.levelno)
        if color is None:
            return line
        return f"{color}{line}{_RESET}"


class Logger:
    """全局日志静态类，封装 logging.Logger。"""

    _instance: logging.Logger | None = None

    @classmethod
    def _EnsureLoaded(cls) -> None:
        if cls._instance is not None:
            return
        cls._instance = logging.getLogger("Mango")
        cls._instance.setLevel(logging.DEBUG)
        if not cls._instance.handlers:
            handler = logging.StreamHandler(sys.stderr)
            handler.setLevel(logging.DEBUG)
            fmt = _ColoredFormatter(
                "[%(asctime)s] [%(levelname)-5s] [%(name)s] %(message)s",
                datefmt="%H:%M:%S",
            )
            handler.setFormatter(fmt)
            cls._instance.addHandler(handler)

    # ---- 公开方法 ----

    @classmethod
    def Info(cls, msg: str, *args: object) -> None:
        cls._EnsureLoaded()
        cls._instance.info(msg, *args)

    @classmethod
    def Warning(cls, msg: str, *args: object) -> None:
        cls._EnsureLoaded()
        cls._instance.warning(msg, *args)

    @classmethod
    def Error(cls, msg: str, *args: object) -> None:
        cls._EnsureLoaded()
        cls._instance.error(msg, *args)

    @classmethod
    def Debug(cls, msg: str, *args: object) -> None:
        cls._EnsureLoaded()
        cls._instance.debug(msg, *args)

    # ---- 日志级别控制 ----

    @classmethod
    def SetLevel(cls, level: int) -> None:
        cls._EnsureLoaded()
        cls._instance.setLevel(level)

    @classmethod
    def RedirectToStdout(cls) -> None:
        """CLI 单窗口模式：将日志输出从 stderr 重定向到 stdout。"""
        cls._EnsureLoaded()
        for handler in cls._instance.handlers:
            if isinstance(handler, logging.StreamHandler):
                handler.stream = sys.stdout

    @classmethod
    def GetLogger(cls) -> logging.Logger:
        """返回底层 logging.Logger，供需要定制格式的场景使用。"""
        cls._EnsureLoaded()
        return cls._instance
