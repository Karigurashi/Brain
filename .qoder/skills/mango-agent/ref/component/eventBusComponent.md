# EventBusComponent + AgentStreamEvent

## EventBusComponent

**定义**：Agent 流式事件总线组件，继承 `SyncEventBus<AgentStreamEvent>` 泛型基类，同时实现 `IComponent` 生命周期接口。供外部监听器实时订阅 Agent 运行事件。

**职责**：
- 提供同步事件发布/订阅机制（Push / Subscribe / Unsubscribe）
- 作为 Agent 内部各组件推送运行时事件的统一通道
- OnDestroy 时自动清空所有监听器

**核心流程**：
- 外部调用方通过 `Subscribe(callback)` 注册监听器
- Agent 内部通过 `Push(event)` 推送事件
- 监听器同步收到回调

---

## AgentStreamEvent

**定义**：Agent 流式事件数据类（dataclass），供外部实时渲染的标准化事件。

**事件类型（EAgentStreamEventType）**：
- TURN_START：推理轮次开始
- THINKING_DELTA / THINKING_COMPLETE：思考链增量 / 完成
- TEXT_DELTA / TEXT_COMPLETE：文本增量 / 完成
- TOOL_START / TOOL_RESULT：工具调用开始 / 结果
- STATE_CHANGE：Agent 状态迁移
- COMPACTION：上下文压缩事件
- ERROR：错误事件
- DONE：本轮结束

**核心流程**：
- 每种事件类型对应一个静态工厂方法（如 `TextDelta(content)`、`ToolStart(name, args)` 等）
- 事件通过 EventBusComponent.Push() 推送给所有订阅者
