"""InjectionComponent —— 将后台产生的内容注入 Agent，由运行锁自然排队。"""

from __future__ import annotations

from typing import TYPE_CHECKING

from agent.component.loop.loopComponent import LoopComponent
from agent.core.baseComponent import BaseComponent

if TYPE_CHECKING:
    from agent.core.baseAgent import BaseAgent


class InjectionComponent(BaseComponent):
    """后台内容注入组件 —— 将内容作为独立 Run 注入 Agent。

    由 ScheduleComponent / WorkflowComponent 等后台任务消费者调用。
    注入的 Run 经 LoopComponent.CreateTask 创建：Agent 忙时在运行锁上
    FIFO 排队，当前 Run 完成后自动唤醒执行；Task 统一登记，Destroy 时
    批量取消。无需忙闲判断与 DONE 事件冲刷。
    """

    def OnInitialize(self, agent: BaseAgent) -> None:
        self._agent: BaseAgent = agent
        self._loopComp = agent.GetComponent(LoopComponent)

    def InjectAsync(self, content: str) -> None:
        """将内容作为独立 Run 注入 Agent；忙时在运行锁上自然排队。

        Args:
            content: 待注入的文本内容。
        """
        self._loopComp.CreateTask(self._agent.RunAsync(content))
