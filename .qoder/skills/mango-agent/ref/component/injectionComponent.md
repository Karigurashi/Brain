# InjectionComponent

## 定义

后台内容注入组件 —— 将后台产生的内容（定时任务触发、Workflow 完成回调）作为独立 Run 注入 Agent 主循环。由 `ScheduleComponent` / `WorkflowComponent` 等后台任务消费者调用。

## 职责

- 提供 `InjectAsync(content)` 接口，将文本内容作为新 Run 注入 Agent
- 通过 `LoopComponent.CreateTask` 创建独立 Run 的协程 Task
- 利用 `runLock` 自然排队：Agent 忙时 FIFO 等待，完成后自动唤醒

## 核心处理流程

### InjectAsync(content)
1. 调用 `LoopComponent.CreateTask(self._agent.RunStreamAsync(content))`
2. Task 在 Agent 所属 loop 中调度
3. 若 Agent 正忙（runLock 被持有），新 Task 在锁上排队等待
4. 当前 Run 完成后，锁释放，排队的 Task 自动获取锁开始执行
