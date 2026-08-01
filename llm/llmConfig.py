"""LLM 配置对象，与 settings.json 中 model 节结构一一对应。

LLMConfig — 模型配置列表的容器类型（由 Settings 内部使用）。
LLMModel  — 单个模型条目。
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class LLMConfig:
    """模型配置列表的容器类型。

    由 Settings 内部使用，通过 SerializeUtil.FromDict 反序列化。

    Attributes:
        models: 模型配置列表。
        defaultModel: 默认模型名。
        timeout: 请求超时秒数。
        maxRetries: 框架层 LLM 重试最大次数。
        retryBaseDelay: 重试基础等待秒数。
        retryMaxDelay: 重试最大等待秒数。
    """

    models: list[LLMModel] = field(default_factory=list)
    defaultModel: str = ""
    timeout: float = 120.0
    maxRetries: int = 3
    retryBaseDelay: float = 1.0
    retryMaxDelay: float = 30.0


@dataclass
class LLMModel:
    """单一 LLM 的连接与运行时配置。

    多余字段通过 LLMConfig.__post_init__ 过滤，不会传入构造函数。

    重试策略由 LLMConfig 全局统一管理，不在单模型级别配置。

    Attributes:
        name: 配置别名，用于在调度器中按名称查找。
        url: 模型 API 端点地址（base URL）。
        apiKey: 认证密钥。
        provider: 厂商标识（openai / anthropic / gemini）。
        modelName: 实际模型名，缺省时沿用 name。
        thinkingBudget: Anthropic Extended Thinking 预算 token 数。
    """

    name: str
    url: str
    apiKey: str
    provider: str = ""
    modelName: str = ""
    thinkingBudget: int = 4000

    def __post_init__(self) -> None:
        """modelName 缺省时沿用 name。"""
        if not self.modelName:
            self.modelName = self.name

