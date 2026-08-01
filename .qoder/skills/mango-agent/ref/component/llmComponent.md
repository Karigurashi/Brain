# LLMComponent

## 定义

将 `BaseLLM` 封装为可挂载的 `IComponent`，持有 BaseLLM、工具绑定、用量追踪和四维调用能力。挂载到 BaseAgent 后自动可用。

## 职责

- 持有 `BaseLLM` 实例，提供 `InvokeAsync`（非流式）和 `StreamAsync`（流式）两种调用模式
- 工具绑定：`BindTools(toolSpecs)` 设置 LLM 可用工具列表
- 用量追踪：累计 promptTokens / completionTokens，计算缓存命中率
- Token 估算：`EstimateTokens(messages)` / `EstimateText(text)` 基于 TokenEstimator
- 流式调用时内部管理缓冲区（StringIO 复用），自动推送 TextDelta / ThinkingDelta / TextComplete / ThinkingComplete 事件
- 消息归一化：`FromStr` / `FromDicts` / `FromChatMessages` 三种明确签名

## 核心处理流程

### OnInitialize
1. 从 `DataComponent` 获取 `BaseLLM` 实例
2. 注入 `EventBusComponent`（用于事件推送）
3. 配置 `TokenEstimator`（按模型名匹配编码器）

### StreamAsync(messages, turnIndex, cancellationToken)
1. 重置内容缓冲区和思考链缓冲区（复用 StringIO）
2. 逐 chunk 流式接收 LLM 响应
3. thinkingContent → 写入思考缓冲区 → 推送 ThinkingDelta
4. content → 写入内容缓冲区 → 推送 TextDelta
5. toolCalls → 累积
6. 流结束后推送 TextComplete / ThinkingComplete
7. 记录最后 usage（promptTokens / completionTokens / cacheHitRate）
8. 返回 `ChatResponse(content, reasoningContent, toolCalls, usage)`

### InvokeAsync(messages, turnIndex, cancellationToken)
1. 调用 `BaseLLM.InvokeAsync` 获取完整响应
2. 推送 TextComplete / ThinkingComplete
3. 记录 usage 统计
4. 返回 `ChatResponse`
