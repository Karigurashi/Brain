# SkillComponent

## 定义

Skill 管理组件 —— 持有 Skill 注册表与文件加载器，支持**渐进式披露**（Layer 1 前缀注入 + Layer 2 按需加载）。对标 Claude Code SKILL.md 架构。

## 职责

- Skill 注册/注销（Register / Unregister）
- 文件系统加载（LoadFromDirectory / LoadSingleFile）
- **Layer 1**：`GetAllPrefixes()` 返回 name + description 清单，注入 system prompt
- **Layer 2**：`LoadSkill(name)` 返回完整 SOP 正文，由 `load_skill` 工具触发
- 工具白名单管理：`GetAllowedToolNames()` 返回激活 Skill 的 allowedTools 并集

## 核心处理流程

### LoadFromDirectory(directory)
1. `SkillLoader.ScanDirectory` 扫描目录下所有 SKILL.md
2. 获取所有 Skill 对象
3. 逐个 Register

### GetAllPrefixes（Layer 1 渐进式披露）
1. 遍历所有已注册 Skill
2. 调用 `skill.GetPrefix()` 获取 name + description
3. 合并为前缀清单文本
4. 注入到 System Prompt（RESIDENT）

### LoadSkill(name)（Layer 2 渐进式披露）
1. 按名称查找 Skill
2. 返回 `skill.GetContent()`（完整 SOP 正文，带 `<skill>` 标签包裹）
3. 由 `load_skill` 工具作为 Tool Result 注入上下文
