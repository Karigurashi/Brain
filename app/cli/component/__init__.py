"""CLI 领域组件包 —— 终端平台行为的组件化拆分。

- platform: 平台 SPI 实现与组件编排。
- console: 终端模式初始化（UTF-8 / ANSI / QuickEdit）。
- render: Agent 事件渲染与固定版面打印。
- input: prompt_toolkit 行输入（编辑 / 历史 / 粘贴）。
- repl: REPL 主循环与中断分流。
- command: CLI 指令上下文（终端即时输出）。
"""
