"""大模型代理调度管理器。

从 Settings 统一配置自动创建对应 Provider（OpenAI / Anthropic / Gemini），
管理 Provider 连接池，按名称分发 BaseLLM。
"""

from __future__ import annotations

from setting import Settings
from .baseLLM import BaseLLM
from .llmConfig import LLMModel
from .provider.anthropic import AnthropicProvider
from .provider.gemini import GeminiProvider
from .provider.openai import OpenAIProvider


class LLMManager:
    """大模型调度管理器（静态类）。

    通过 Settings 读取全局 settings.json 配置，首次 GetProvider 时自动懒加载。
    同一模型只保有一个 Provider 连接，通过 GetProvider 分发 BaseLLM。

    使用方式::

        from llm import LLMManager

        # 按名称获取 Provider（首次调用自动加载配置）
        provider = LLMManager.GetProvider("gpt-4")
        response = provider.Invoke([ChatMessage.User("Hello")])
    """

    _providers: dict[str, BaseLLM] = {}
    _loaded: bool = False
    _defaultModelOverride: str | None = None  # 运行时覆盖的默认模型

    # ==================== 懒加载 ====================

    @classmethod
    def _EnsureLoaded(cls) -> None:
        """首次访问时初始化所有 Provider。"""
        if cls._loaded:
            return
        cls._providers.clear()

        for model in Settings.Models():
            provider = cls._CreateProvider(model)
            cls._providers[model.name] = provider

        cls._loaded = True

    @classmethod
    def InitFromPath(cls, jsonPath: str) -> None:
        """手动初始化：传入 settings.json 配置文件路径，重新加载全部配置。

        可多次调用以切换配置，每次调用会清空已有的 Provider。

        Args:
            jsonPath: settings.json 格式的配置文件路径。

        Raises:
            FileNotFoundError: 配置文件不存在。
        """
        Settings.InitFromPath(jsonPath)
        cls._loaded = False
        cls._EnsureLoaded()

    @classmethod
    def _CreateProvider(cls, config: LLMModel) -> BaseLLM:
        """根据 LLMModel 创建对应的 BaseLLM 实例。

        provider 优先取 config.provider，为空时根据 URL 自动推断。
        重试参数从 Settings 全局读取，所有模型共享同一份配置。
        """
        providerType = config.provider or cls._InferProvider(config.url)
        retryKwargs = {
            "maxRetries": Settings.MaxRetries(),
            "retryBaseDelay": Settings.RetryBaseDelay(),
            "retryMaxDelay": Settings.RetryMaxDelay(),
            "timeout": Settings.Timeout(),
        }

        if providerType == "anthropic":
            return AnthropicProvider(config, **retryKwargs)
        elif providerType == "gemini":
            return GeminiProvider(config, **retryKwargs)
        else:
            return OpenAIProvider(config, **retryKwargs)

    @staticmethod
    def _InferProvider(url: str) -> str:
        """根据 URL 自动推断 provider 类型。"""
        urlLower = url.lower()
        if "anthropic" in urlLower:
            return "anthropic"
        if "gemini" in urlLower or "google" in urlLower:
            return "gemini"
        return "openai"

    # ==================== Provider 获取 ====================

    @classmethod
    def GetProvider(cls, name: str | None = None) -> BaseLLM:
        """按模型名获取 BaseLLM Provider。

        首次调用时自动懒加载 settings.json 配置。
        name 为空时自动回退到 Settings 中的 defaultModel。

        Returns:
            BaseLLM 实例，可直接调用 Invoke / Stream / InvokeAsync / StreamAsync。
        """
        cls._EnsureLoaded()
        name = name or Settings.DefaultModel()
        if name not in cls._providers:
            raise KeyError(f"Model '{name}' not found. Available: {cls.ListModels()}")
        return cls._providers[name]

    # ==================== 模型管理 ====================

    @classmethod
    def GetConfig(cls, name: str) -> LLMModel:
        """按名称获取模型配置。"""
        return Settings.GetModel(name)

    @classmethod
    def ListModels(cls) -> list[str]:
        """获取所有已注册模型的名称列表。"""
        cls._EnsureLoaded()
        return list(cls._providers.keys())

    @classmethod
    def AddModel(cls, model: LLMModel) -> None:
        """动态添加模型并创建 Provider。"""
        cls._EnsureLoaded()
        Settings.Models().append(model)
        cls._providers[model.name] = cls._CreateProvider(model)

    @classmethod
    def RemoveModel(cls, name: str) -> None:
        """动态移除模型及其 Provider。"""
        cls._EnsureLoaded()
        model = Settings.GetModel(name)
        Settings.Models().remove(model)
        cls._providers.pop(name, None)

    @classmethod
    def DefaultModel(cls) -> str:
        """获取默认模型名（优先运行时覆盖，否则取 Settings 默认）。"""
        if cls._defaultModelOverride:
            return cls._defaultModelOverride
        return Settings.DefaultModel()

    @classmethod
    def SetDefaultModel(cls, value: str) -> None:
        """设置默认模型名（运行时覆盖，不持久化）。"""
        cls._EnsureLoaded()
        if value and value not in cls._providers:
            raise KeyError(f"Cannot set default: model '{value}' not registered.")
        cls._defaultModelOverride = value

    # ==================== 资源清理 ====================

    @classmethod
    def Close(cls) -> None:
        """关闭所有 Provider 的同步连接池。"""
        for p in cls._providers.values():
            if hasattr(p, "Close"):
                p.Close()

    @classmethod
    async def CloseAsync(cls) -> None:
        """关闭所有 Provider 的异步连接池。"""
        for p in cls._providers.values():
            if hasattr(p, "CloseAsync"):
                await p.CloseAsync()
