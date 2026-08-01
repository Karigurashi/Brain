# ToolComponent + BaseTool

## ToolComponent

**定义**：Tool 管理组件 —— 持有工具注册表并实现调度分发。挂载到 BaseAgent 后自动可用，支持装饰器注册、外部扩展、LLM 工具绑定、调度分发。对标 Claude Code Tool 调度机制。

**职责**：
- **两层注册表**：类级 `_toolClasses`（@Register 装饰器，全局共享）+ 实例级 `_tools`（外部注册，实例隔离）
- 装饰器注册：`@ToolComponent.Register` 自动注册工具类
- 外部注册：`RegisterTool()` 接受已实例化的工具对象
- 按需实例化：`Get(name)` 优先返回已实例化，其次从类注册创建并缓存
- 工具启用/禁用：`Disable(name)` / `Enable(name)` / `DisableByCategory(category)`
- ToolSpec 导出：`GetAllToolSpecs()` 直接给 LLM 绑定
- 调度分发：`DispatchAsync(toolCall)` 含超时控制；`DispatchBatchAsync(toolCalls)` 批量并发，单工具失败不取消其余
- 执行统计：记录各工具耗时 + 调用次数

**核心处理流程**：

### 装饰器注册 (@Register)
1. 工具类 import 时触发装饰器
2. 按 `toolClass.name` 注册到类级 `_toolClasses` 字典

### Get(name)
1. 若 name 在 `_disabled` → 返回 None
2. 若 name 在实例级 `_tools` → 返回已缓存实例
3. 若 name 在类级 `_toolClasses` → 实例化、缓存、返回
4. 都不存在 → 返回 None

### DispatchAsync(toolCall)
1. 按 toolCall.name 查找工具
2. 解析超时值：实例 timeout > 类 timeout > 全局 _defaultTimeout
3. 注入 `_agent` 引用
4. 有超时：`asyncio.wait_for(tool.ExecuteAsync(...), timeout)`
5. 无超时：直接 `await tool.ExecuteAsync(...)`
6. 记录执行耗时 + 调用计数
7. 超时 / 异常 → 返回 ToolResult.Fail

### DispatchBatchAsync(toolCalls)
1. 每个 toolCall 包装为 `_SafeDispatch`（异常隔离）
2. `asyncio.gather(*tasks)` 并发执行
3. 返回按输入顺序的 ToolResult 列表

---

## BaseTool

**定义**：工具抽象基类 —— 所有工具必须继承此基类。子类覆盖类属性声明元数据，实现 `_Invoke` / `_InvokeAsync` 定义行为。

**职责**：
- **元数据声明**：name / description / parameters（LLM function calling 规格）、category、timeout
- **上下文控制**：resultLodLevel（结果 LOD 等级）、skipPersist（跳过落盘）
- **双轨执行**：`_Invoke`（同步主逻辑）+ `_InvokeAsync`（异步，默认回退到线程池执行 _Invoke）
- **公共入口**：`ExecuteAsync` 统一对外，优先 `_InvokeAsync`，回退 `_Invoke`
- **ToolSpec 缓存**：`ToToolSpec()` 首次调用后类级缓存，避免每轮 ReAct 重复分配

**核心流程**：

### ExecuteAsync(**kwargs)
1. 调用 `_InvokeAsync(**kwargs)`
2. 默认 `_InvokeAsync` 在线程池中执行 `_Invoke`（`asyncio.to_thread`）
3. 返回 `ToolResult`

### ToToolSpec
1. 检查类级 `_cachedToolSpec` 缓存
2. 未缓存 → 创建 `ToolSpec(name, description, parameters)`
3. 缓存到类级变量
4. 返回
