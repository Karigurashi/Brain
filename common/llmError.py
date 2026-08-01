"""LLM 调用异常，携带完整错误上下文用于排查。"""

from __future__ import annotations

from typing import Optional


class LLMError(RuntimeError):
    """LLM 调用失败异常，保留 HTTP 状态码与响应体。

    Attributes:
        message: 人类可读的错误描述。
        provider: provider 名称 (openai / anthropic / gemini)。
        model: 模型名称。
        statusCode: HTTP 状态码，None 表示网络层错误。
        responseBody: 服务端返回的原始响应体文本。
    """

    def __init__(
        self,
        message: str,
        provider: str = "",
        model: str = "",
        statusCode: Optional[int] = None,
        responseBody: Optional[str] = None,
    ) -> None:
        super().__init__(message)
        self.provider = provider
        self.model = model
        self.statusCode = statusCode
        self.responseBody = responseBody

    def __str__(self) -> str:
        parts = [super().__str__()]
        if self.provider:
            parts.append(f"provider={self.provider}")
        if self.model:
            parts.append(f"model={self.model}")
        if self.statusCode is not None:
            parts.append(f"status={self.statusCode}")
        if self.responseBody:
            bodyPreview = self.responseBody[:500]
            parts.append(f"body={bodyPreview}")
        return " | ".join(parts)
