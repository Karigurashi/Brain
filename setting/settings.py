"""全局设置静态类 —— 模块导入时自动加载 settings.json。

Settings 以原始 dict 存储各模块配置节，通过泛型 Get 按需解析为类型化对象。

使用方式::

    from setting import Settings

    # 泛型解析 channel 下各 App 配置（失败回退类型默认值）
    cliConfig = Settings.Get("channel.cli", CliConfig)
    feishuConfig = Settings.Get("channel.feishu", FeishuAppConfig)

    # 便捷访问器
    models = Settings.Models()
    config = Settings.AgentConfig()
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any, Type, TypeVar

from common import SerializeUtil
from common.const import ERoad
from llm.llmConfig import LLMConfig, LLMModel
from agent.component.data.agentConfig import AgentConfig

T = TypeVar("T")


class Settings:
    """全局设置静态类，模块导入时自动加载 settings.json。

    支持通过 InitFromPath 手动切换配置路径或热加载。
    原始 JSON 以 dict 存储，按节名用泛型 Get 解析。

    模块划分：
    - model：LLM 模型列表 + 全局 LLM 参数（超时、重试）
    - agent：Agent 运行时配置（Token 预算、压缩、落盘等）
    - channel：各 Channel App 配置（``feishu`` / ``cli`` 等），App Config 自身继承 ChannelConfig
    """


    SETTINGS_PATH: str = str(Path(ERoad.WORKSPACE) / ERoad.SETTINGS_JSON)

    _data: dict[str, Any] = {}
    # model 节缓存：LLMManager 可能原地增删 Models() 列表
    _llmConfig: LLMConfig = LLMConfig()

    # ==================== 加载 ====================

    @classmethod
    def InitFromPath(cls, jsonPath: str) -> None:
        """手动切换配置路径，立即重新加载。

        可多次调用以热切换配置，每次调用会清空已有数据。

        Args:
            jsonPath: settings.json 格式的配置文件路径。

        Raises:
            FileNotFoundError: 配置文件不存在。
        """
        cls._LoadFromPath(jsonPath)

    @classmethod
    def _LoadFromPath(cls, jsonPath: str) -> None:
        """从指定 JSON 路径加载全部模块配置。"""
        if not Path(jsonPath).exists():
            raise FileNotFoundError(f"Settings file not found: {jsonPath}")

        content = Path(jsonPath).read_text(encoding="utf-8")
        data = SerializeUtil.FromJson(content)
        cls._data = data if isinstance(data, dict) else {}
        cls._llmConfig = SerializeUtil.FromDict(cls._data.get("model") or {}, LLMConfig)

    # ==================== 泛型解析 ====================

    @classmethod
    def Get(cls, section: str, configType: Type[T]) -> T:
        """将 settings 指定节解析为 ``configType`` 实例。

        Args:
            section: JSON 键路径，支持点号，如 ``"agent"`` / ``"channel.feishu"``。
            configType: 目标 dataclass / Pydantic 类型。

        Returns:
            解析后的新实例。节缺失、非 dict 或反序列化失败时返回 ``configType()`` 默认值。
        """
        try:
            return SerializeUtil.FromDict(cls.Raw(section), configType)
        except Exception:
            return configType()


    @classmethod
    def Raw(cls, section: str) -> dict[str, Any]:
        """返回指定节的原始 dict 浅拷贝；支持点路径。"""
        current: Any = cls._data
        for part in section.split("."):
            if not part:
                continue
            if not isinstance(current, dict):
                return {}
            current = current.get(part)
        if not isinstance(current, dict):
            return {}
        return dict(current)


    # ==================== model 模块 ====================

    @classmethod
    def Models(cls) -> list[LLMModel]:
        """获取所有模型配置列表。"""
        return cls._llmConfig.models

    @classmethod
    def GetModel(cls, name: str) -> LLMModel:
        """按名称查找模型配置。

        Raises:
            KeyError: 模型不存在。
        """
        for model in cls._llmConfig.models:
            if model.name == name:
                return model
        raise KeyError(
            f"Model '{name}' not found. Available: {cls.ListModelNames()}"
        )

    @classmethod
    def ListModelNames(cls) -> list[str]:
        """获取所有已注册模型的名称列表。"""
        return [m.name for m in cls._llmConfig.models]

    @classmethod
    def DefaultModel(cls) -> str:
        """获取默认模型名。"""
        if not cls._llmConfig.defaultModel and cls._llmConfig.models:
            return cls._llmConfig.models[0].name
        return cls._llmConfig.defaultModel

    @classmethod
    def Timeout(cls) -> float:
        """请求超时秒数。"""
        return cls._llmConfig.timeout

    @classmethod
    def MaxRetries(cls) -> int:
        """框架层 LLM 重试最大次数。"""
        return cls._llmConfig.maxRetries

    @classmethod
    def RetryBaseDelay(cls) -> float:
        """重试基础等待秒数。"""
        return cls._llmConfig.retryBaseDelay

    @classmethod
    def RetryMaxDelay(cls) -> float:
        """重试最大等待秒数。"""
        return cls._llmConfig.retryMaxDelay

    # ==================== agent 模块 ====================

    @classmethod
    def AgentConfig(cls) -> AgentConfig:
        """获取默认 Agent 运行时配置。

        每次调用返回浅拷贝，调用方可安全修改。
        """
        return copy.copy(cls.Get("agent", AgentConfig))

    # ==================== 资源清理 ====================

    @classmethod
    def Reset(cls) -> None:
        """重置所有缓存，重新加载配置。"""
        cls._data = {}
        cls._llmConfig = LLMConfig()
        cls._LoadFromPath(cls.SETTINGS_PATH)


# 模块导入时自动加载默认配置
Settings._LoadFromPath(Settings.SETTINGS_PATH)
