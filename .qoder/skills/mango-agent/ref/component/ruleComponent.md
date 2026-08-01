# RuleComponent

## 定义

规则管理组件 —— 将所有规则文件（.md / .mdc）直接注入 Context。挂载到 BaseAgent 后，加载 rulesDir 目录下的规则文件全部注入为 RESIDENT System Prompt。

## 职责

- 从目录批量加载 .md / .mdc 规则文件
- `GetAlwaysApplyBody()`：获取所有已加载规则的合并正文，自动将相对链接解析为绝对路径
- 规则清空（Clear）

## 核心处理流程

### LoadFromDirectory(directory)
1. 遍历目录下所有 .md / .mdc 文件
2. 读取文件内容
3. 存入 `_entries` 列表（body + sourcePath）
4. 返回加载数量

### GetAlwaysApplyBody
1. 遍历 `_entries`
2. 通过 `FileUtils.ResolveRelativeLinks(body, sourcePath)` 将相对链接解析为绝对路径
3. 合并所有规则正文
4. 返回合并文本
