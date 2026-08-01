"""Channel 内置指令 —— 所有平台通用的 12 个指令。

由 BaseChannel.__init__ 自动注册到 CommandRegistry，各平台 Channel 无需手动注册。
指令 handler 仅依赖 CommandContext 服务化 API，不感知 Agent 或其组件。
"""

from __future__ import annotations

from .command import Command
from .commandContext import CommandContext
from .commandRegistry import CommandRegistry


def RegisterBuiltinCommands(registry: CommandRegistry) -> None:
    """注册全部内置指令到 registry。"""
    registry.Register(Command("help", "Show available commands", _HelpAsync, aliases=["h"]))
    registry.Register(Command("clear", "Clear conversation history", _ClearAsync, aliases=["c"]))
    registry.Register(Command("compact", "Trigger context compaction", _CompactAsync))
    registry.Register(Command("model", "List or switch model", _ModelAsync, aliases=["m"]))
    registry.Register(Command("cost", "Show token usage", _CostAsync))
    registry.Register(Command("status", "Show agent status", _StatusAsync, aliases=["s"]))
    registry.Register(Command("sessions", "List sessions", _SessionsAsync))
    registry.Register(Command("session", "Save session to file", _SessionAsync))
    registry.Register(Command("tools", "List registered tools", _ToolsAsync, aliases=["t"]))
    registry.Register(Command("config", "Show agent configuration", _ConfigAsync))
    registry.Register(Command("reload", "Rebuild harness (reload rules/skills/MCP tools)", _ReloadAsync))
    registry.Register(Command("exit", "Exit", _ExitAsync, aliases=["quit", "q"]))


# ==================== /help ====================

async def _HelpAsync(ctx: CommandContext, args: str) -> None:
    """打印所有可用指令及描述。"""
    ctx.Print("Available commands:")
    ctx.PrintDim(ctx.Registry.GetHelpText())


# ==================== /clear ====================

async def _ClearAsync(ctx: CommandContext, args: str) -> None:
    """清空当前会话对话历史，保留常驻规则与技能。"""
    sessionId = ctx.ClearSession()
    ctx.Print(f"Conversation cleared. Session: #{sessionId}")
    ctx.PrintDim("System rules and skills are preserved.")


# ==================== /compact ====================

async def _CompactAsync(ctx: CommandContext, args: str) -> None:
    """手动触发上下文压缩。"""
    ctx.PrintDim("Compacting context...")
    tokenSaved = await ctx.CompactContextAsync(force=True)
    if tokenSaved > 0:
        ctx.Print(f"Compaction freed {tokenSaved} tokens.")
    else:
        ctx.PrintDim("Compaction not required (within budget).")


# ==================== /model ====================

async def _ModelAsync(ctx: CommandContext, args: str) -> None:
    """列出可用模型或切换到指定模型。

    /model            → 列表
    /model <name>     → 切换
    """
    from llm import LLMManager

    modelName = args.strip()
    if not modelName:
        _PrintModelList(ctx)
        return

    if ctx.SwitchModel(modelName):
        newLlm = LLMManager.GetProvider(modelName)
        ctx.Print(f"Switched to {modelName} ({newLlm.modelName})")
    else:
        ctx.PrintError(
            f"Unknown model: {modelName}. Available: {', '.join(LLMManager.ListModels())}"
        )


def _PrintModelList(ctx: CommandContext) -> None:
    """打印可用模型列表，标记当前模型。"""
    from llm import LLMManager

    current = ctx.GetModelName()
    models = LLMManager.ListModels()
    ctx.PrintDim("Available Models:")
    for name in models:
        llm = LLMManager.GetProvider(name)
        marker = "*" if llm.modelName == current else " "
        ctx.Print(f" {marker} {name}  ({llm.modelName})")
    ctx.PrintDim("Use /model <name> to switch.")


# ==================== /cost ====================

async def _CostAsync(ctx: CommandContext, args: str) -> None:
    """显示 Token 用量统计。"""
    ctx.Print("Token Usage:")
    ctx.PrintDim(f"  Input:      {ctx.FormatK(ctx.GetTotalPromptTokens())}")
    ctx.PrintDim(f"  Output:     {ctx.FormatK(ctx.GetTotalCompletionTokens())}")
    ctx.PrintDim(f"  Total:      {ctx.FormatK(ctx.GetTotalPromptTokens() + ctx.GetTotalCompletionTokens())}")
    ctx.PrintDim(f"  Cache Hit:  {ctx.GetLastCacheHitRate():.1f}%")


# ==================== /status ====================

async def _StatusAsync(ctx: CommandContext, args: str) -> None:
    """显示 Agent 运行时状态。"""
    ctx.Print("Agent Status:")
    ctx.PrintDim(f"  Model:        {ctx.GetModelName()} ({ctx.GetProviderName()})")
    ctx.PrintDim(f"  Session:      #{ctx.GetActiveSessionId()} ({ctx.GetSessionMessageCount(ctx.GetActiveSessionId())} messages)")
    ctx.PrintDim(f"  Est. Tokens:  {ctx.FormatK(ctx.GetLastPromptTokens())}")
    ctx.PrintDim(f"  Tools:        {ctx.GetToolCount()} registered")


# ==================== /sessions ====================

async def _SessionsAsync(ctx: CommandContext, args: str) -> None:
    """列出所有会话，标记活跃。"""
    activeId = ctx.GetActiveSessionId()
    ids = ctx.GetSessionIds()
    ctx.PrintDim(f"Sessions ({len(ids)}):")
    for sid in sorted(ids):
        marker = "*" if sid == activeId else " "
        count = ctx.GetSessionMessageCount(sid)
        ctx.PrintDim(f" {marker} #{sid} ({count} messages)")
    ctx.PrintDim("Use /session to save current session.")


# ==================== /session ====================

async def _SessionAsync(ctx: CommandContext, args: str) -> None:
    """将当前 session 以人类可读 Markdown 格式写入 memory/sessions/YYYY-MM-DD/{sessionId}.md。"""
    count = ctx.SaveSessionToMarkdown()
    if count > 0:
        ctx.Print(f"Session saved ({count} messages)")
    else:
        ctx.PrintError("No active session or save failed.")


# ==================== /tools ====================

async def _ToolsAsync(ctx: CommandContext, args: str) -> None:
    """按分类列出已注册工具。"""
    tools = ctx.GetAllTools()
    if not tools:
        ctx.PrintDim("No tools registered.")
        return

    categories: dict[str, list[dict]] = {}
    for tool in tools:
        cat = tool["category"]
        if cat not in categories:
            categories[cat] = []
        categories[cat].append(tool)

    ctx.PrintDim(f"Registered Tools ({len(tools)}):")
    for cat in sorted(categories):
        ctx.Print(f"  {cat}:")
        for t in categories[cat]:
            ctx.PrintDim(f"    {t['name']}  - {t['description']}")


# ==================== /config ====================

async def _ConfigAsync(ctx: CommandContext, args: str) -> None:
    """显示当前 Agent 配置。"""
    config = ctx.GetAgentConfig()

    ctx.Print("Agent Configuration:")
    ctx.PrintDim(f"  Workspace Root: {config.workspaceRoot}")
    ctx.PrintDim(f"  Max Turns:      {config.maxTurns}")
    ctx.PrintDim(f"  Token Budget:   {ctx.FormatK(config.effectiveBudget)}")
    ctx.PrintDim(f"  Persist Enable: {config.enablePersist}")
    ctx.PrintDim(f"  Skills Dir:     {config.skillsDir}")
    ctx.PrintDim(f"  Rules Dir:      {config.rulesDir}")
    ctx.PrintDim(f"  Tasks Dir:      {config.tasksDir}")


# ==================== /reload ====================

async def _ReloadAsync(ctx: CommandContext, args: str) -> None:
    """重建 harness：重载 rules / skills / MCP 工具配置并重新绑定到 LLM。"""
    ctx.PrintDim("Rebuilding harness...")
    try:
        toolCount = await ctx.RebuildHarnessAsync()
        ctx.Print(f"Harness rebuilt ({toolCount} tools registered).")
    except Exception as exc:
        ctx.PrintError(f"Harness rebuild failed: {exc}")


# ==================== /exit ====================

async def _ExitAsync(ctx: CommandContext, args: str) -> None:
    """请求退出 Channel。"""
    from ..lifecycle import LifecycleComponent
    ctx.Channel.GetComponent(LifecycleComponent).RequestStop()
