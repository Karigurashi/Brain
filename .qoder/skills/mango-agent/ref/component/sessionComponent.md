# SessionComponent + Session

## SessionComponent

**定义**：Agent 运行时的 Session 管理器，管理多个 `Session` 实例，维护一个活跃 Session 引用。作为 IComponent 可挂载到 BaseAgent。

**职责**：
- **"账本管理员"**：持有多个 Session，每个 Session 完整记录所有消息（含压缩摘要）
- Session 生命周期管理：创建（NewSession）、切换（SwitchSession）、清除（ClearSession）、移除（RemoveSession）
- 会话持久化：保存为 JSON/Markdown 到 memory/sessions/ 目录
- 消息管理代理：Append / AppendBatch / ClearLod4 / ApplyCompactionResult / FixOrphanedToolCalls

**核心处理流程**：

### NewSession
1. 归档当前活跃 Session（持久化到 Memory）
2. 创建新 Session 实例
3. 从旧 Session 拷贝 RESIDENT 常驻内容到新 Session

### SwitchSession(sessionId)
1. 查找目标 Session
2. 归档当前活跃 Session
3. 将目标设为活跃

### SaveToMemory / SaveToMarkdown
1. 收集活跃 Session 的 RESIDENT + 对话消息
2. 序列化为 JSON / 格式化 Markdown
3. 通过 MemoryComponent 写入文件

### ReadFromMemory(sessionId)
1. 从 MemoryComponent 读取 session 文件
2. JSON 反序列化为 `Session` 对象
3. 返回重建的 Session

---

## Session

**定义**：会话数据对象，消息的唯一归属地。纯数据容器，封装单次会话的全部消息、压缩状态和元数据。

**职责**：
- 维护两段消息列表：`residentMessages`（RESIDENT 常驻）+ `conversationMessages`（非 RESIDENT 对话）
- 消息追加按 LOD 级别路由到对应列表
- 支持压缩结果替换（ApplyCompactionResult，保留 RESIDENT 不可触碰）
- 孤儿 tool_call 修复（FixOrphanedToolCalls）：反向遍历，删除无对应 TOOL 响应的 tool_call
- LOD4 消息清除（ClearLod4）：从后往前遍历，清除 EXTERNAL_ONLY 消息并剥离关联 tool_call
- 全量序列化/反序列化（ToJson / FromJson）

**核心流程**：

### Append(msg)
1. LOD == RESIDENT → 写入 `_residentMessages`
2. LOD != RESIDENT → 写入 `_conversationMessages`
3. LOD == EXTERNAL_ONLY → `lod4Count++`

### ApplyCompactionResult(compactedMessages)
1. Clear 保留 RESIDENT
2. 追加压缩产物中的非 RESIDENT 消息

### FixOrphanedToolCalls
1. 反向遍历 conversationMessages
2. 收集 TOOL 消息的 toolCallId → validIds
3. 对 ASSISTANT 消息，过滤 toolCalls 保留 validIds 中的项
4. 删除空壳 ASSISTANT（无 content 且 toolCalls 全被清理）
