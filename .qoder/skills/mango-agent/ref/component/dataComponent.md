# DataComponent + AgentConfig + EAgentState

## DataComponent

**定义**：Agent 运行时数据组件，统一管理 Agent 运行时的配置数据、状态机和 LLM 实例。

**职责**：
- 持有 `AgentConfig` 配置（循环行为、Token 预算、路径配置等）
- 管理 `EAgentState` 状态机（setter 校验合法转移，非法仅警告不阻断）
- 持有 `BaseLLM` 实例
- 提供自增 `agentId`

**核心流程**：
- 构造时 agentId 自增，config 默认拷贝 `AgentConfig.DEFAULT`
- state setter 通过 `VALID_TRANSITIONS` 校验状态转移合法性，非法转移仅 Warning

---

## AgentConfig

**定义**：Agent 运行时统一配置（单一扁平 dataclass），所有字段均为不可变类型。

**职责**：
- 循环行为：maxTurns / tokenBudget / runTimeout
- 路径配置：workspaceRoot / skillsDir / rulesDir / mcpJsonPath / memoryDir / storeDir / mangoIgnorePath
- Token 预算：maxTokens / reserveTokens
- 压缩参数：compactThreshold / keepRecentTurns / coldOffloadGraceSeconds / summaryMaxTokens / batchSummaryMaxTokens
- 落盘参数：enablePersist / persistCharThreshold / persistPreviewChars / storeMaxTotalSize / storeMaxFileCount
- 子系统开关：enableWorkflow / enableSchedule

**核心流程**：
- `__post_init__` 中空值自动填充 workspaceRoot + 默认子路径
- `effectiveBudget` 属性：tokenBudget > 0 时直接使用，否则按 maxTokens - reserveTokens 计算

---

## EAgentState

**定义**：Agent 运行时状态枚举（IntEnum），控制状态迁移。

**状态值**：
- IDLE(0)：初始 / 等待用户输入
- THINKING(1)：LLM 推理中
- ACTING(2)：工具执行中
- WAITING_USER(3)：需用户确认（预留）
- FINISHED(4)：本轮正常结束
- ERROR(5)：异常终止

**核心流程**：
- `VALID_TRANSITIONS` 字典定义合法状态转移表
- IDLE → THINKING / ERROR
- THINKING → ACTING / FINISHED / ERROR / WAITING_USER
- ACTING → THINKING / FINISHED / ERROR
- 终态（FINISHED / ERROR）可通过 IDLE 复位
