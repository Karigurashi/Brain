# ContextComponent + ContextCompactor + ContextMessage + EContextLodLevel

## ContextComponent

**定义**：上下文引擎 —— SessionComponent 与 LLM 之间的调度器。不存储任何消息，消息的唯一归属地是 SessionComponent。

**职责**：
- 编排四阶段生命周期：**Ingest → Assemble → Compact → AfterTurn**
- 摄入时构造 `ContextMessage` 并写入 SessionComponent
- 组装时从 SessionComponent 读取、过滤、组织为 ChatMessage 列表
- 超预算时触发压缩，委托 `ContextCompactor` 执行
- 工具结果落盘（PersistToolResult）：超阈值写入 StoreComponent 并返回预览

**四阶段核心流程**：

### Ingest(role, content, lodLevel, toolCalls, ...)
1. lodLevel 未传入时按 role 自动判定（SYSTEM→RESIDENT, TOOL→DISCARDABLE, USER/ASSISTANT→SUMMARIZABLE）
2. 构造 `ContextMessage`
3. 写入 `SessionComponent.Append()`

### PersistToolResult(content, skipPersist)
1. 若未超 persistCharThreshold → 原样返回
2. 超阈值 + enablePersist + 非 skipPersist → StoreComponent.Store() + 返回预览
3. 超阈值但无法落盘 → 截断预览

### AssembleAsync
1. 读取 SessionComponent 的 residentMessages + conversationMessages
2. 若 estimated >= effectiveBudget → 触发 `CompactAsync(force=True)`
3. 将所有 ContextMessage 的 chatMessage 收集到 ChatMessage 列表
4. 返回 ChatMessage 列表

### CompactAsync(force)
1. 计算阈值（effectiveBudget × compactThreshold）
2. 未超阈值且非强制 → 跳过
3. 超阈值：委托 `ContextCompactor.ManageCapacityAsync`
4. 应用压缩结果到 SessionComponent
5. `FixOrphanedToolCalls()` 清理孤儿 tool_call
6. 推送 Compaction 事件

### AfterTurnAsync
- 清除所有 LOD4(EXTERNAL_ONLY) 消息（`SessionComponent.ClearLod4()`）

### AutoColdOffloadIfNeeded
- 每轮对话前检查宽限期（最后消息距当前时间是否超 coldOffloadGraceSeconds）
- 未超宽限期 → 跳过（保护 DeepSeek 等 Provider 的 Prompt Cache）
- 超宽限期 → 对 Session 执行 LOD2+LOD3 冷卸载

---

## ContextCompactor

**定义**：统一容量管理器，按三优先级释放 token 直到满足预算。

**职责**：
- 优先级 1（零成本）：冷 LOD2(DISCARDABLE) 落盘占位 + LOD3(LATEST_ONLY) 只留最后 1 条
- 优先级 2（有成本）：SUMMARIZABLE → LLM 批量摘要，保留语义
- 优先级 3（兜底）：硬截断，从旧到新丢弃非 RESIDENT
- LOD0/RESIDENT 任何情况下都不可触碰

**核心流程**（ManageCapacityAsync）：

1. 估算当前 token 数
2. 未超预算 + 非强制 → 直接返回
3. **第一优先级 - OffloadColdLod2InPlace**：
   - LOD2：从后往前保留最近 `keepRecentTurns` 条 DISCARDABLE，其余落盘/占位（ContentStore 不可用时退化为 `[aged:XKB]`）
   - LOD2 关联的 Thinking 内容同步清理
   - LOD3：倒序仅保留最后 1 条 LATEST_ONLY，其余删除
4. **第二优先级 - _SummarizeAsync**：
   - 收集 SUMMARIZABLE 消息（排除与保留 DISCARDABLE 关联的 ASSISTANT tool_calls 以避孤儿化）
   - 批量调用 LLM 生成摘要
   - 剥离 `<analysis>` 草稿区，保留 `<summary>` 正文
   - 用摘要 + 幸存消息替换原始列表
5. **第三优先级 - _HardTruncateInPlace**：
   - Pass 1：从旧到新丢弃 DISCARDABLE（工具结果）
   - Pass 2：从旧到新丢弃 SUMMARIZABLE 非摘要
   - Pass 3：最后丢弃压缩摘要自身

---

## ContextMessage

**定义**：Session 中存储的标准消息类型，带唯一 ID 和 LOD 标记。role/content 直接复用 ChatMessage。

**属性**：
- `messageId`：数值型 UUID
- `chatMessage`：关联的 ChatMessage 实例
- `lodLevel`：LOD 等级
- `createdAt`：创建时间戳
- `isAgedOut`：是否已被冷卸载
- `isSummary`：是否为压缩摘要消息
- `skipPersist`：是否跳过 ContentStore 落盘

---

## EContextLodLevel

**定义**：LOD 五级分级枚举（IntEnum），控制上下文内容的压缩与丢弃策略。

| 级别 | 名称 | 语义 | 压缩策略 | 丢弃策略 |
|------|------|------|---------|---------|
| 0 | RESIDENT | 常驻不压缩 | 不可压缩 | 不可丢弃 |
| 1 | SUMMARIZABLE | 可压缩为摘要 | LLM 摘要 | 不可丢弃 |
| 2 | DISCARDABLE | 可落盘占位 | 冷卸载落盘 | 可丢弃 |
| 3 | LATEST_ONLY | 只留最后 1 条 | 删旧留新 | 可丢弃 |
| 4 | EXTERNAL_ONLY | 当轮注入次轮丢弃 | 不压缩 | 次轮丢弃 |
