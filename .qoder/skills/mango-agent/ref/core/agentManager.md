# AgentManager

## 定义

Agent 快捷创建工厂（静态类），封装 `LLMManager.GetProvider` + `Settings.AgentConfig` 组装 + `Agent` 实例化三步流程，提供一行代码创建 Agent / SimpleAgent 的便捷入口。

## 职责

- 封装 LLM 获取与 Agent 实例化流程，屏蔽 LLMManager 与 AgentConfig 组装细节
- config 为 None 时自动使用 `Settings.AgentConfig()` 默认配置
- 提供 `CreateSubAgent` 创建工作流子 Agent（禁用 Skill/Rule/MCP）

## 核心流程

### CreateAgent(modelName, config)
1. 通过 `LLMManager.GetProvider(modelName)` 获取 BaseLLM 实例
2. config 为 None 时使用 `Settings.AgentConfig()` 默认配置
3. 返回 `Agent(llm, config)`

### CreateSubAgent(modelName)
1. 获取 BaseLLM
2. 创建 AgentConfig（skillsDir=""、rulesDir=""、mcpJsonPath=""）
3. 返回禁用扩展的 Agent 实例
