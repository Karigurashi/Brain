# McpComponent

## 定义

MCP Server 管理组件 —— 持有 MCP Server 配置注册表，支持 stdio / http / sse 三种传输协议。对标 Claude Code MCP 的 Server 管理。

## 职责

- MCP Server 配置注册（Register / Unregister / Get / GetAll）
- `.mcp.json` 批量加载与导出
- 真实连接与工具发现（`ConnectAllAsync`）：并行启动所有已启用 Server，握手、发现工具、注册为可调用工具
- 子进程生命周期管理：OnDestroy 终止全部 MCP 子进程
- 工具白名单过滤 + 上限截断

## 核心处理流程

### LoadFromMCPJson(filePath)
1. 读取 .mcp.json 文件
2. 解析 `mcpServers` 字典
3. 对每个 Server 配置创建 `McpServerConfig`
4. Register 到注册表

### ConnectAllAsync
1. 整体超时保护（30s），超时返回空列表
2. 并行启动所有已启用 Server
3. 单 Server 异常隔离，不影响其余

### _ConnectOneServerAsync(server)
1. **stdio 传输**：验证 launchCommand → 创建 `McpStdioClient` → StartAsync → InitializeAsync
2. **http/sse 传输**：验证 url → 创建 `McpHttpClient` → StartAsync → InitializeAsync
3. **工具发现**：`ListToolsAsync` 获取工具列表
4. **白名单过滤**：按 server.tools 白名单过滤
5. **上限截断**：按 server.toolsMax 截断
6. 将发现的工具包装为 `McpTool` 实例
7. client 加入 `_clients` 管理

### OnDestroy
1. 遍历 `_clients`，逐个 `Terminate()`
2. 清空注册表
