# Agent 编排器

## 定义

继承 `BaseAgent`，将 `BaseLLM` + `SessionComponent` + `ContextComponent` + `HarnessComponent` + 工具注册表组装为完整的 ReAct Agent，驱动 **Think → Act → Observe** 循环。对标 Claude Code Agent 调度机制。

## 职责

- 管理完整的 ReAct 推理循环（用户消息摄入 → LLM 推理 → 工具调度 → 结果回写）
- 生命周期包装：无论正常结束、异常、取消还是超限，finally 中 `AfterTurnAsync` 必定执行
- 运行锁保护：通过 `LoopComponent.runLock` 保证单 Agent 实例同时仅一个 Run 在执行
- 事件推送：通过 `EventBusComponent` 推送 StateChange / TurnStart / ToolStart / ToolResult / Error / Done

## 核心处理流程

### 统一入口 _RunGuardedAsync

1. 获取 `runLock`（asyncio.Lock），排他执行
2. try 中执行 `_RunReActCoreAsync`
3. 正常退出：记录 normalExit=True
4. 异常退出：推送 ErrorEvent，打印 traceback，向上传播
5. finally：`AfterTurnAsync()`（清除 LOD4 过期消息），异常退出时额外推送 ERROR + DONE

### ReAct 核心循环 _RunReActCoreAsync

1. **Build Harness**：`HarnessComponent.BuildAsync()` 装填 RESIDENT 块
2. **冷卸载检测**：`AutoColdOffloadIfNeeded()` 检查宽限期
3. **摄入用户消息**：`ContextComponent.Ingest(USER, ...)`
4. **循环执行**（直到 maxTurns 耗尽或 LLM 返回纯文本）：
   a. TurnStart 事件
   b. BuildStatusBar → Ingest 到上下文
   c. `AssembleAsync()` 组装消息列表
   d. 流式 / 非流式 LLM 调用
   e. 若取消 / 错误 → 终止
   f. 若 toolCalls 为空 → 纯文本响应，退出循环
   g. `_ExecuteToolCallsAsync()` 批量并发执行工具
   h. 工具结果摄入上下文
5. **终止处理**：maxTurns 超限 → Error 事件；正常结束 → FINISHED + Done

### 工具执行 _ExecuteToolCallsAsync

1. 推送 ToolStart 事件（每个 toolCall）
2. `ToolComponent.DispatchBatchAsync()` 批量并发分发
3. 推送 ToolResultEvent（每个结果）
4. 摄入 ASSISTANT（含 toolCalls + thinkingContent）
5. 逐个摄入 TOOL 结果，根据工具的 `resultLodLevel` 决定 LOD 等级
