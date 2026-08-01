# ScheduleComponent

## 定义

Agent 侧定时任务管理组件，封装 `ScheduleRegistry`（CronScheduler + JSON 持久化）+ 回注机制。仅在 `enableSchedule=True` 时由 `HarnessComponent.BuildAsync` 挂载并启用相关工具。

## 职责

- 定时任务创建/删除：`CreateScheduleTask(name, expression, prompt)` / `DeleteTask(specId)`
- 任务查询：`GetSpec` / `ListSpecs`
- Cron 到点回调：触发时更新统计、持久化、通过 `InjectionComponent` 注入 prompt
- OnDestroy 时清理所有定时器

## 核心处理流程

### OnInitialize
1. 从 DataComponent 获取 tasksDir 配置
2. 创建 `ScheduleRegistry(tasksDir)`（CronScheduler + JSON 持久化）
3. 注入 `InjectionComponent`
4. `RestoreAll(_OnFire)`：从磁盘恢复所有已持久化的定时任务，注册到 CronScheduler

### CreateScheduleTask(name, expression, prompt)
1. 委托 `ScheduleRegistry.CreateAgentWake` 创建定时任务
2. Cron 表达式校验
3. 持久化到 JSON 文件
4. 注册到 CronScheduler，绑定 `_OnFire` 回调

### _OnFire(spec) — Cron 到点回调
1. 更新 `spec.lastFiredAt` / `spec.fireCount`
2. 持久化更新
3. 构造 `<task_schedule>` 块（Name + prompt）
4. 通过 `InjectionComponent.InjectAsync(content)` 注入 Agent 主循环

### OnDestroy
1. `ScheduleRegistry.Clear()` — 取消所有 Cron 定时器 + 清空持久化记录
