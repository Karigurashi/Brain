# SimpleAgent

## 定义

纯对话 Agent，继承 `BaseAgent`，跳过所有 harness 功能（rules、skills、MCP、context compaction），仅保留 BaseAgent 四维调用接口。事件通过 `EventBusComponent` 推送。

## 职责

- 提供轻量级单轮 LLM 对话能力，不涉及 ReAct 循环
- 流式事件推送与缓冲区管理已下沉至 `LLMComponent.StreamAsync`
- SimpleAgent 仅负责状态编排（THINKING → FINISHED / ERROR）

## 核心处理流程

### RunStreamAsync(userMessage, cancellationToken, systemPrompt)

1. 推送 THINKING 状态
2. 构建消息列表（可选 systemPrompt + userMessage）
3. 调用 `LLMComponent.StreamAsync`（内部管理缓冲区 + 推送 ThinkingDelta / TextDelta 事件）
4. 异常时推送 ErrorEvent + ERROR 状态
5. 正常结束推送 FINISHED + Done
