"""Agent 运行时统一配置 —— 单一扁平 dataclass。

按功能域分组，所有字段均为不可变类型（int/float/bool/str/NoneType）。
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from common.const import ERoad


# ---- 内置默认压缩 Prompt ----

DEFAULT_BATCH_SUMMARY_PROMPT = (
    "<task>\n"
    "Distill the conversation below (wrapped in <conversation>) into a single "
    "structured summary. This summary will replace the original messages and become "
    "the agent's sole memory of this portion of the conversation.\n"
    "Do not include anything else.\n"
    "</task>\n\n"
    "<output_structure>\n"
    "Your summary must follow these 9 sections exactly:\n\n"
    "1. Primary Request and Intent — all user requests, including implicit goals.\n"
    "2. Key Technical Concepts — technologies, frameworks, architectural decisions, and their rationale.\n"
    "3. Files and Code Sections — every file examined/modified/created, with full paths, "
    "key code snippets, and why each was accessed. Prioritize recent work.\n"
    "4. Errors and Fixes — every error, how it was resolved. "
    "Preserve error messages, stack traces, and line numbers verbatim.\n"
    "5. Problem Solving — problems solved, ongoing troubleshooting, "
    "and approaches tried and abandoned (with reasons).\n"
    "6. All User Messages — ALL non-tool-result user messages verbatim. "
    "These capture corrections, preference changes, and evolving intent.\n"
    "7. Pending Tasks — tasks explicitly requested but not yet completed.\n"
    "8. Current Work — precisely what was being worked on immediately before this summary: "
    "file names, code snippets, exact work-in-progress state.\n"
    "9. Optional Next Step — only if directly aligned with the user's latest explicit request. "
    "Include verbatim quotes from the conversation to justify it.\n"
    "</output_structure>\n\n"
    "<rules>\n"
    "<retention>\n"
    "MUST preserve verbatim:\n"
    "- Architecture decisions and key constraints.\n"
    "- Modified file paths and change records.\n"
    "- Verification results (pass/fail) and test outcomes.\n"
    "- Unresolved TODOs and rollback notes.\n"
    "- Identifiers: UUIDs, hashes, IPs, ports, URLs, commit hashes, PR numbers.\n"
    "- Specific data from tool outputs that informed decisions (error codes, measurements, counts).\n"
    "</retention>\n"
    "<drop>\n"
    "Safe to omit or condense:\n"
    "- Transitional acknowledgments (\"Got it\", \"Let me look\").\n"
    "- Failed attempts where the approach was abandoned (keep only the final approach and reason).\n"
    "- Tool outputs that produced no actionable information.\n"
    "- Redundant content repeated across messages.\n"
    "</drop>\n"
    "<integrity>\n"
    "Never oversimplify. \"Sutskever left OpenAI in May 2024\" must not become \"Sutskever left.\" "
    "Dates, names, version numbers, and quantifiable specifics are the information — not optional details.\n"
    "</integrity>\n"
    "</rules>\n\n"
    "<re_compaction>\n"
    "The conversation may contain previous summaries wrapped in <compactHistory>. "
    "Treat ALL content — old summaries and new messages alike — as raw material. "
    "Do not skip or further condense previous summaries. "
    "Re-evaluate everything and produce one fresh, complete summary following the structure above.\n"
    "</re_compaction>\n\n"
    "Respond with only the summary. Do not include anything else."
)


@dataclass
class AgentConfig:
    """Agent 运行时统一配置。
    
    按功能域分组的扁平 dataclass，所有字段均为不可变类型。
    """
    
    # -- 循环行为 --
    maxTurns: int = 99                      # 单次 Run 最大推理轮次，-1 表示无限制
    tokenBudget: int = 0                    # ContextComponent 组装预算（0 则用 maxTokens - reserveTokens）
    runTimeout: float = 0.0                 # 单次 Run 最大执行秒数，0 表示不限
    stream: bool = True                     # RunAsync 默认是否流式（调用方可显式传入覆盖）
    
    # -- 路径配置 --
    workspaceRoot: str = ""                 # 工作区根目录（空则用默认 workspace）
    skillsDir: str = ""                     # Skill 扫描目录（空则 workspaceRoot/skills）
    rulesDir: str = ""                      # Rule 扫描目录（空则 workspaceRoot/rules）
    memoryDir: str = ""                     # 记忆持久化目录（空则 workspaceRoot/memory/）
    tasksDir: str = ""                      # 定时任务 JSON 目录（空则 workspaceRoot/tasks）
    storeDir: str = ""                      # 内容外存目录（空则 workspaceRoot/.store/）
    subAgentDir: str = ""                   # 子 Agent 扫描目录（空则 workspaceRoot/subagent）
    mcpJsonPath: str = ""                   # MCP 配置文件路径（空则 workspaceRoot/.mcp.json）
    mangoIgnorePath: str = ""               # .mangoIgnore 路径（空则 workspaceRoot/.mangoIgnore）
    
    # -- Token 预算 --
    maxTokens: int = 200000                # Token 预算上限
    reserveTokens: int = 4096              # 为模型回复预留的 token 数
    
    # -- 压缩参数 --
    compactThreshold: float = 0.85         # 触发压缩的上下文占用率阈值（0.0-1.0）
    keepRecentTurns: int = 3               # 冷卸载时保留的最近 DISCARDABLE 条数
    coldOffloadGraceSeconds: int = 900     # 冷卸载宽限期（秒）
    summaryMaxTokens: int = 1024           # 单条消息摘要 LLM 最大输出 token
    batchSummaryMaxTokens: int = 8192      # 批量压缩摘要 LLM 最大输出 token
    compactionPrompt: str | None = None    # LLM 压缩时的自定义 prompt（None 则用内置默认）
    
    # -- 落盘参数 --
    enablePersist: bool = True             # 是否启用大结果落盘+预览
    persistCharThreshold: int = 50000      # 触发落盘的字符数阈值
    persistPreviewChars: int = 5000        # 预览截断字符数
    storeMaxTotalSize: int = 5000 * 1024 * 1024       # 外存目录总容量上限（超限LRU淘汰，默认500MB）
    storeMaxFileCount: int = 1000           # 外存目录最大文件数（超限LRU淘汰，默认100）
    
    # -- 子系统开关 --
    enableWorkflow: bool = False            # 是否启用 Workflow 子系统（开启后注入 run_workflow 等编排工具）
    enableSchedule: bool = False            # 是否启用定时任务子系统（开启后注入 createTask / deleteTask 工具）

    # -- 外部密钥 --
    tavilyApiKey: str = ""  # Tavily Search API 密钥

    # ---- 初始化后处理 ----

    def __post_init__(self) -> None:
        """空值自动填充 workspaceRoot + 默认子路径，传了则原样保留。"""
        if not self.workspaceRoot:
            self.workspaceRoot = str(ERoad.WORKSPACE)

        if not self.skillsDir:
            self.skillsDir = os.path.join(self.workspaceRoot, str(ERoad.SKILLS_DIR))
        if not self.rulesDir:
            self.rulesDir = os.path.join(self.workspaceRoot, str(ERoad.RULES_DIR))
        if not self.mcpJsonPath:
            self.mcpJsonPath = os.path.join(self.workspaceRoot, str(ERoad.MCP_JSON_PATH))
        if not self.memoryDir:
            self.memoryDir = os.path.join(self.workspaceRoot, str(ERoad.MEMORY_DIR))
        if not self.tasksDir:
            self.tasksDir = os.path.join(self.workspaceRoot, str(ERoad.TASKS_DIR))
        if not self.storeDir:
            self.storeDir = os.path.join(self.workspaceRoot, str(ERoad.STORE_DIR))
        if not self.subAgentDir:
            self.subAgentDir = os.path.join(self.workspaceRoot, str(ERoad.SUBAGENT_DIR))
        if not self.mangoIgnorePath:
            self.mangoIgnorePath = os.path.join(self.workspaceRoot, str(ERoad.MANGO_IGNORE))

    # ---- 属性 ----

    @property
    def effectiveBudget(self) -> int:
        """实际可用于上下文组装的 token 预算。

        tokenBudget > 0 时直接使用，否则按 maxTokens - reserveTokens 计算。
        """
        if self.tokenBudget > 0:
            return self.tokenBudget
        return self.maxTokens - self.reserveTokens


# 默认配置单例（每次 copy 使用，避免共享修改）
AgentConfig.DEFAULT = AgentConfig()
