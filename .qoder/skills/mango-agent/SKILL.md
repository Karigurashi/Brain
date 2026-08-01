---
name: mango-agent
description: Mango Agent 框架架构参考。涵盖 Agent 组件化架构、ReAct 循环调度、上下文管理、工具注册分发、Skill/Rule/MCP 扩展机制。当需要理解或修改 Agent 框架代码、添加新 Component、调整 ReAct 循环行为、或了解各组件职责与协同时使用。
---

# Mango Agent 框架

## 架构概览

Mango Agent 是一个基于 **Component 组合模式** 的 ReAct Agent 框架。所有能力（LLM 调用、上下文管理、工具调度、会话持久化等）均封装为独立的 `IComponent` 子类，通过 `BaseAgent` 的容器统一管理生命周期。

```
Agent (ReAct 主编排)
 ├── LoopComponent         # 协程调度上下文（runLock + Task 管理 + 跨线程投递）
 ├── EventBusComponent     # 流式事件总线（TEXT_DELTA / TOOL_START / DONE 等）
 ├── DataComponent         # 运行时数据（AgentConfig + 状态机 + LLM 实例）
 ├── LLMComponent          # LLM 调用封装（流式/非流式 + 缓冲区 + 事件推送）
 ├── SessionComponent      # 会话管理器（多 Session + 持久化 + 消息管理）
 ├── ContextComponent      # 上下文引擎（Ingest → Assemble → Compact → AfterTurn）
 ├── HarnessComponent      # 多层 Context 注入管道（Skill/Rule/MCP/Tool 装填）
 ├── RuleComponent         # 规则加载（.md/.mdc → RESIDENT System Prompt）
 ├── SkillComponent        # 渐进式 Skill 披露（Layer1 前缀 + Layer2 按需加载）
 ├── McpComponent          # MCP Server 管理（stdio/http/sse 连接 + 工具发现）
 ├── ToolComponent         # 工具注册与调度（装饰器注册 + 超时控制 + 批量并发）
 ├── MemoryComponent       # 跨会话持久化记忆（sessions/ + INDEX.md 注入）
 ├── StoreComponent        # 大内容文件缓存落盘（LRU 淘汰）
 ├── InjectionComponent    # 后台内容注入（Schedule/Workflow → Agent 主循环）
 ├── ScheduleComponent     # 定时任务管理（Cron + 持久化 + 回注）
 └── WorkflowComponent     # Workflow 后台任务管理（提交/取消/结果回注）
```

## 核心概念

### Component 生命周期

所有 Component 遵循统一的生命周期契约：
- **构造函数**：仅做字段默认值初始化，不接收业务参数
- **OnInitialize(agent)**：挂载时自动调用，通过 `agent.GetComponent()` 注入依赖
- **OnDestroy()**：卸载时回调，用于资源清理

### 四维调用接口

`BaseAgent` 定义抽象接口 `RunStreamAsync(userMessage, cancellationToken)`，子类实现差异化行为：
- **Agent**：完整 ReAct 循环（Think → Act → Observe），含 harness 装填、上下文压缩、工具调度
- **SimpleAgent**：纯对话，跳过所有 harness 功能，单轮 LLM 调用

### ReAct 循环流程

```
RunStreamAsync → BuildAsync(harness) → AutoColdOffload → Ingest(USER)
  → LOOP: AssembleAsync → LLM Stream/Invoke → DispatchBatchAsync(toolCalls) → Ingest(ASSISTANT+TOOL)
  → AfterTurnAsync(ClearLod4) → DONE
```

## 详细参考

各组件的定义、职责与核心处理流程详见以下文档：

### Core（核心类）

| 模块 | 参考文件 |
|------|----------|
| 核心基础 | [core-foundation.md](ref/core/core-foundation.md) |
| Agent 编排器 | [agent.md](ref/core/agent.md) |
| AgentManager 工厂 | [agentManager.md](ref/core/agentManager.md) |
| SimpleAgent | [simpleAgent.md](ref/core/simpleAgent.md) |

### Component（组件）

| 模块 | 参考文件 |
|------|----------|
| DataComponent + 配置 + 状态机 | [dataComponent.md](ref/component/dataComponent.md) |
| EventBusComponent + 事件 | [eventBusComponent.md](ref/component/eventBusComponent.md) |
| LoopComponent | [loopComponent.md](ref/component/loopComponent.md) |
| LLMComponent | [llmComponent.md](ref/component/llmComponent.md) |
| SessionComponent + Session | [sessionComponent.md](ref/component/sessionComponent.md) |
| ContextComponent + 压缩 | [contextComponent.md](ref/component/contextComponent.md) |
| HarnessComponent | [harnessComponent.md](ref/component/harnessComponent.md) |
| RuleComponent | [ruleComponent.md](ref/component/ruleComponent.md) |
| SkillComponent | [skillComponent.md](ref/component/skillComponent.md) |
| McpComponent | [mcpComponent.md](ref/component/mcpComponent.md) |
| ToolComponent + BaseTool | [toolComponent.md](ref/component/toolComponent.md) |
| MemoryComponent | [memoryComponent.md](ref/component/memoryComponent.md) |
| StoreComponent | [storeComponent.md](ref/component/storeComponent.md) |
| InjectionComponent | [injectionComponent.md](ref/component/injectionComponent.md) |
| ScheduleComponent | [scheduleComponent.md](ref/component/scheduleComponent.md) |
| WorkflowComponent | [workflowComponent.md](ref/component/workflowComponent.md) |
