# 核心基础

## BaseAgent

**定义**：Agent 体系抽象基类，内置 Component 容器，通过组合模式持有各 `IComponent` 子类实例。

**职责**：
- 提供 Component 生命周期管理（AddComponent / GetComponent / RemoveComponent / Destroy）
- 定义抽象接口 `RunStreamAsync`，子类实现差异化行为（ReAct 循环 / 纯对话）
- Component 间调用必须通过 `GetComponent()` 获取，不得将 Component 作为参数传递

**核心流程**：
1. `AddComponent<T>()` — 无参构造实例，注册时自动触发 `OnInitialize` 完成依赖注入
2. `GetComponent<T>()` — 若未创建则自动构造并初始化（懒加载）
3. `RemoveComponent / Destroy` — 调用 `OnDestroy()`，执行清理

## IComponent

**定义**：所有可挂载模块必须实现的抽象接口，定义挂载 / 卸载生命周期。

**职责**：
- 构造函数：MUST NOT 接收业务参数，仅做字段默认值初始化
- `OnInitialize(agent)`：真正的初始化入口，通过 `agent.GetComponent()` 注入依赖
- `OnDestroy()`：卸载时回调，用于资源清理

**核心流程**：
- `BaseAgent.AddComponent<T>() / GetComponent<T>()` 内部无参构造实例后自动触发 `OnInitialize(agent)`
- `RemoveComponent / Destroy` 时调用 `OnDestroy()`

## FileUtils

**定义**：静态工具类，提供文件系统辅助方法（如相对链接解析为绝对路径）。
