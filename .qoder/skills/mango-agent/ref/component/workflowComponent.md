# WorkflowComponent

## 定义

Agent 侧 Workflow 后台任务管理组件，管理 Workflow 的提交、取消和结果查询。仅在 `enableWorkflow=True` 时由 `HarnessComponent.BuildAsync` 启用相关工具。

## 职责

- Workflow 提交：`AddTask(wf)` 将 Workflow 包装为后台 `TaskT<WorkflowResult>` 并调度执行
- 任务取消：`Cancel(taskId)` 取消运行中的 Workflow
- 结果查询：`GetTask` / `GetTaskResult` / `FormatTaskResult`
- 完成回调：Workflow 完成时自动落盘结果 + 通过 `InjectionComponent` 注入 Agent 主循环

## 核心处理流程

### OnInitialize
1. 创建 `TaskScheduler` 实例
2. 注入 `InjectionComponent`

### AddTask(wf)
1. 分配 taskId
2. 创建 `TaskT(wf.ExecuteAsync, taskId, name)`
3. `scheduler.Schedule(task)` 调度执行，绑定 `_OnTaskFinished` 回调
4. 返回 Task 句柄

### _OnTaskFinished(handle) — Workflow 完成回调
1. 获取 WorkflowResult
2. 提取最后一条事件消息
3. 将完整结果通过 `StoreComponent.Store` 落盘
4. 构造 `<task_flow>` 块（Name + 事件消息 + Store 路径）
5. 通过 `InjectionComponent.InjectAsync(msg)` 注入 Agent 主循环

### OnDestroy
1. `scheduler.CancelAll()` — 取消所有运行中的 Workflow
