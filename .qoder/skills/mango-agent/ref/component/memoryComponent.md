# MemoryComponent

## 定义

跨会话持久化记忆组件，作为 IComponent 可挂载到 BaseAgent。提供会话摘要持久化（写 sessions/YYYY-MM-DD/{sessionId}.md）和 INDEX.md 上下文注入（LOD0）。

**目录结构**：
```
{workspace/memory/}/
    sessions/               # 不可变会话摘要（按日期子目录）
        YYYY-MM-DD/
            {sessionId}.md
    memory/                 # 持久记忆
        INDEX.md            # 导航索引（LOD0 注入入口）
        LOG.md              # 追加式操作日志
```

## 职责

- Session 持久化：`SaveToMemory` 将格式化内容写入 sessions/ 目录
- Session 读取：`ReadSession` 读取已保存的 session 文件
- Context 注入：`LoadContextBlocks` 从 INDEX.md 加载 LOD0 上下文块
- 内部持有 `MemoryStore`（文件 I/O）和 `MemoryIndex`（索引解析）

## 核心处理流程

### OnInitialize
1. 从 DataComponent 获取 memoryDir 配置
2. 创建 `MemoryStore(memoryDir)` — 文件存储
3. 创建 `MemoryIndex(store)` — 索引管理

### SaveToMemory(sessionId, body, messageCount, toolsUsed, ...)
1. 构建 frontmatter（元数据）
2. 拼接 frontmatter + body
3. 通过 `MemoryStore.SaveSession` 写入文件（原子写入 + 会话裁剪）
4. 追加 LOG.md 记录

### LoadContextBlocks
1. 委托 `MemoryIndex.ToContextBlocks()`
2. 只加载 INDEX.md（< 500 tokens），不含具体页面内容
3. 返回上下文块列表，由 HarnessComponent 注入为 RESIDENT

### ReadSession(sessionId)
1. 委托 `MemoryStore.ReadSession` 搜索 sessions/*/ 下的文件
2. 剥离 frontmatter
3. 返回正文
