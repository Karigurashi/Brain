# LoopComponent

## 定义

Agent 协程调度上下文，统一承载 Agent 内部全部协程调度行为。强制 **单 Agent 单 Event Loop** 铁律。

## 职责

1. **Loop 归属校验**：首次调度时捕获 running loop，后续严格校验一致性，跨 loop 立即 raise
2. **Task 生命周期管理**：`CreateTask` 统一登记派生 Task，完成自动注销，`OnDestroy` 批量取消
3. **跨线程入口**：`PostFromThread` 封装 `run_coroutine_threadsafe`，是外部线程向 Agent 投递协程的唯一合法通道
4. **运行互斥锁**：`runLock` 惰性创建，绑定所属 loop，保证单实例同时仅一个 Run 执行

## 核心处理流程

### runLock（属性访问）
1. 首次访问时调用 `_BindLoop` 捕获 running loop
2. 惰性创建 `asyncio.Lock()`
3. 后续在其他 loop 中访问立即 raise

### CreateTask(coro)
1. `_BindLoop` 校验 loop 一致性
2. `asyncio.create_task` 创建 Task
3. 登记到 `_tasks` 集合
4. 添加 `done_callback`：完成时自动注销
5. 返回 Task

### PostFromThread(coro)
1. 校验 loop 已绑定
2. 调用 `asyncio.run_coroutine_threadsafe(coro, loop)`
3. 返回 `concurrent.futures.Future`，可跨线程等待

### OnDestroy
1. 遍历 `_tasks`，逐个 `cancel()`
2. 清空集合
