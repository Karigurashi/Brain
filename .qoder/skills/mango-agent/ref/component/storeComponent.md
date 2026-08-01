# StoreComponent

## 定义

文件缓存落盘组件，负责大内容的外部文件存储、加载、LRU 淘汰管理。当工具返回大结果时，原始内容写入外部文件，上下文中仅保留路径引用 + 预览摘要。

## 职责

- 大内容落盘：`Store(content)` 原子写入外存文件（tmpfile + os.replace 并发安全）
- 按路径加载：`Load(path, refreshAccess)` 读取外存内容，可选刷新 mtime 用于 LRU 排序
- 预览生成：`BuildPersistedPreview(path, content, previewChars)` 生成 `<persisted-output>` 标签格式的预览文本
- LRU 淘汰：`Evict()` 按最近访问时间淘汰超出容量/文件数限制的文件
- 高水位/低水位策略：达到阈值 1.5 倍时触发淘汰，清理至 1.0 倍

## 核心处理流程

### OnInitialize
1. 从 DataComponent.config 读取 storeDir / storeMaxTotalSize / storeMaxFileCount
2. enablePersist 为 False 时 storeDir 为 None，所有操作退化为空

### Store(content, skipEviction)
1. storeDir 为 None → 返回 None
2. 确保目录存在
3. skipEviction 为 False → `_EvictIfNeeded` 检查容量
4. 生成文件名（timestamp + contentHash）
5. 先写 tmpfile，再 os.replace 原子替换

### _EvictIfNeeded(incomingSize, incomingCount)
1. 扫描 storeDir 下所有文件
2. 计算当前容量和文件数
3. 检查是否超限（高水位 1.5 倍阈值）
4. 超限 → 按 mtime 排序，从最旧开始删除
5. 清理至 1.0 倍阈值

### BuildPersistedPreview(path, content, previewChars)
1. 生成 `<persisted-output>` 标签
2. 包含文件路径、大小、预览内容
3. 提示使用 read_file 分段读取
4. 返回预览文本，供 ContextComponent 注入上下文
