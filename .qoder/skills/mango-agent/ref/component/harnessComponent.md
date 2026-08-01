# HarnessComponent + StatusBar + TodoItem

## HarnessComponent

**定义**：多层 Context 注入管道，将各组件的 RESIDENT 块（环境快照、Memory、Rules、Skills 前缀）组装为 `ContextMessage` 列表后写入 Session。挂载到 BaseAgent 后自动获取 RuleComponent / SkillComponent / McpComponent / ToolComponent / DataComponent / SessionComponent。

**职责**：
- `BuildAsync`：一次性装填 RESIDENT 块到 Session（幂等调用）
- 控制工具启停：根据配置 enableWorkflow / enableSchedule 决定 Workflow/Schedule 工具是否可用
- MCP Server 连接与工具发现：`McpComponent.ConnectAllAsync()` → 注册为 ToolComponent 工具
- 绑定工具到 LLM：`LLMComponent.BindTools(toolSpecs)`
- Skill 的 `load_skill` 工具注册
- StatusBar 生成：每轮 `BuildStatusBar(turn)` 生成状态栏文本（时间/轮次/工具计数/TODO）

**核心处理流程**：

### BuildAsync(force)
1. 幂等守卫：已构建且非强制 → 跳过
2. 清空 ToolComponent 实例注册
3. 重新加载 Rules / Skills / MCP 配置（`_ReloadExtensions`）
4. 构建 RESIDENT 消息列表（`_BuildResidentMessages`）：
   - 环境快照（OS 信息）
   - Memory INDEX.md 上下文块
   - Always Apply Rules 合并正文
   - Skills 前缀清单（name + description）
5. 替换 Session 的 residentMessages
6. 注册 `load_skill` 工具
7. MCP Server 连接 + 工具注册
8. 按配置启用/禁用 Workflow / Schedule 工具
9. 绑定工具到 LLMComponent

### BuildStatusBar(turn)
1. turn == 0 时清零工具调用计数
2. 委托 StatusBar.Build(turn, maxTurns, callCounts) 生成状态栏文本

---

## StatusBar

**定义**：状态栏对象，封装时间/轮次/工具计数/TODO 进度的生成与状态管理。HarnessComponent 持有实例。

**职责**：
- `Build(turn, maxTurns, callCounts)` → 生成当轮 `<status>` 块文本
- `UpdateTodos(todos)` → 全量替换 TODO 列表

**核心流程**（Build）：
1. 构建 `<status>` 块
2. 添加当前时间
3. 添加轮次信息（turn/maxTurns）
4. 添加工具调用计数（toolName×count）
5. 添加 TODO 进度（content + status）

---

## TodoItem

**定义**：TODO 条目数据类，由 StatusBar 构造并管理。

**属性**：
- `content`：TODO 描述文本
- `status`：ETodoStatus（PENDING / IN_PROGRESS / COMPLETE / CANCELLED）
