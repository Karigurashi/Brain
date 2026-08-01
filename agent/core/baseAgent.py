"""BaseAgent —— Agent 体系基类，继承 Entity 组合 Component 封装各项能力。

继承 Entity 全部 Component 管理能力，子类实现 RunAsync。
"""

from __future__ import annotations

import abc
from typing import Optional

from common.cancellationToken import CancellationToken
from common.entity.entity import Entity


class BaseAgent(Entity):
    """Agent 体系基类 —— 继承 Entity 的 Component 管理，子类实现 RunAsync。"""

    @abc.abstractmethod
    async def RunAsync(
        self,
        userMessage: str,
        cancellationToken: Optional[CancellationToken] = None,
        stream: Optional[bool] = None,
    ) -> None:
        """异步执行 Agent 主循环，事件通过 EventBusComponent 推送。

        Args:
            userMessage: 用户/外部注入的消息文本。
            cancellationToken: 可选取消令牌。
            stream: True 流式 / False 非流式 / None 使用 AgentConfig.stream。
        """
        ...
