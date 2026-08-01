"""HarnessComponent —— 多层 Context 注入管道，将各组件的 RESIDENT 块组装为 ContextMessage 列表后写入 Session。

挂载到 BaseAgent 后自动获取 RuleComponent / SkillComponent /
McpComponent / ToolComponent / DataComponent / SessionComponent，通过 BuildAsync 完成一次性的 RESIDENT 装填。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import os
import platform
from agent.component.contex.contextMessage import ContextMessage
from agent.component.contex.eContextLodLevel import EContextLodLevel
from agent.component.data.dataComponent import DataComponent
from agent.component.llm.llmComponent import LLMComponent
from agent.component.mcp.mcpComponent import McpComponent
from agent.component.rule.ruleComponent import RuleComponent
from agent.component.session.sessionComponent import SessionComponent
from agent.component.tool.internal.skillTool import SkillTool
from agent.component.skill.skillComponent import SkillComponent
from agent.component.tool.toolComponent import ToolComponent
from agent.component.tool.task import WORKFLOW_TOOL_NAMES, SCHEDULE_TOOL_NAMES
from agent.component.schedule.scheduleComponent import ScheduleComponent
from agent.core.baseComponent import BaseComponent
from .statusBar import StatusBar
from .todoItem import TodoItem
from common.const import ERole
from llm.provider.chatMessage import ChatMessage

if TYPE_CHECKING:
    from agent.core.baseAgent import BaseAgent


class HarnessComponent(BaseComponent):
    """将各 Component 的 RESIDENT 块组装为 ContextMessage 列表并写入 Session。

    挂载后通过 BuildAsync 完成一次性装填：
    - skills 前缀 / MCP 工具描述 / Memory 上下文块 / 环境快照

    路径配置（skillsDir / rulesDir / mcpJsonPath / workspaceRoot）统一从
    DataComponent.config（AgentConfig）读取，无需外部传参。

    用法::

        agent = Agent(llm)
        harness = agent.GetComponent(HarnessComponent)
        count = await harness.BuildAsync()
    """

    _dataComp: DataComponent
    _sessionComp: SessionComponent
    _ruleComp: RuleComponent
    _skillComp: SkillComponent
    _mcpComp: McpComponent
    _toolComp: ToolComponent
    _llmComp: LLMComponent
    _built: bool

    def __init__(self) -> None:
        self._dataComp: DataComponent  # type: ignore[no-redef]
        self._sessionComp: SessionComponent  # type: ignore[no-redef]
        self._ruleComp: RuleComponent  # type: ignore[no-redef]
        self._skillComp: SkillComponent  # type: ignore[no-redef]
        self._mcpComp: McpComponent  # type: ignore[no-redef]
        self._toolComp: ToolComponent  # type: ignore[no-redef]
        self._llmComp: LLMComponent  # type: ignore[no-redef]
        self._built = False
        self._statusBar = StatusBar()

    # ---- BaseComponent 生命周期 ----

    def OnInitialize(self, agent: BaseAgent) -> None:
        """挂载后初始化，自动注入各依赖 Component。"""
        self._agent: BaseAgent = agent
        self._dataComp = agent.GetComponent(DataComponent)
        self._sessionComp = agent.GetComponent(SessionComponent)
        self._ruleComp = agent.GetComponent(RuleComponent)
        self._skillComp = agent.GetComponent(SkillComponent)
        self._mcpComp = agent.GetComponent(McpComponent)
        self._toolComp = agent.GetComponent(ToolComponent)
        self._llmComp = agent.GetComponent(LLMComponent)

    def OnDestroy(self) -> None:
        """从 BaseAgent 卸载时回调，重置构建标记以允许重建。"""
        self._built = False

    # ---- 主入口 ----

    async def BuildAsync(
        self,
        force: bool = False,
    ) -> None:
        """组装全部 RESIDENT Context 块并写入 Session。

        幂等调用：若已成功构建则跳过，避免重复创建 MCP 子进程与重复注册工具。
        设置 force=True 可强制重建（热重载 rules / skills / MCP 配置变更）。

        Args:
            reloadExtensions: 是否从 AgentConfig 指定路径重新加载 extension 注册表。
            force: True 时跳过 _built 守卫强制重建。
        """
        if self._built and not force:
            return

        self._toolComp.Clear()
        self._ReloadExtensions()
        self._sessionComp.ActiveSession.ReplaceResidents(
            self._BuildResidentMessages(),
        )

        if self._skillComp.Count() > 0:
            self._toolComp.RegisterTool(SkillTool())

        # 真实连接 MCP Server，发现并注册其工具为可调用工具
        mcpTools = await self._mcpComp.ConnectAllAsync()
        for mcpTool in mcpTools:
            self._toolComp.RegisterTool(mcpTool)

        # ---- 根据配置控制 Workflow 工具启停（同属 TASK，按工具名） ----
        if self._dataComp.config.enableWorkflow:
            for toolName in WORKFLOW_TOOL_NAMES:
                self._toolComp.Enable(toolName)
        else:
            for toolName in WORKFLOW_TOOL_NAMES:
                self._toolComp.Disable(toolName)

        # ---- 根据配置控制定时任务工具启停 ----
        if self._dataComp.config.enableSchedule:
            self._agent.AddComponent(ScheduleComponent)
            for toolName in SCHEDULE_TOOL_NAMES:
                self._toolComp.Enable(toolName)
        else:
            for toolName in SCHEDULE_TOOL_NAMES:
                self._toolComp.Disable(toolName)

        # ---- 绑定工具到 LLMComponent ----
        toolSpecs = self._toolComp.GetAllToolSpecs()
        if toolSpecs:
            self._llmComp.BindTools(toolSpecs)

        self._built = True

    # ---- 内部 ----

    def _BuildResidentMessages(self) -> list[ContextMessage]:
        """收集全部 RESIDENT 块并构建为 ContextMessage 列表。"""
        residents: list[ContextMessage] = []

        envBlock = self._BuildEnvironmentSnapshot()
        residents.append(self._BuildResidentMessage(envBlock))

        for block in self._sessionComp.memory.LoadContextBlocks():
            if block.strip():
                residents.append(self._BuildResidentMessage(block))

        alwaysBody = self._ruleComp.GetAlwaysApplyBody()
        if alwaysBody.strip():
            residents.append(self._BuildResidentMessage(alwaysBody))

        skillPrefixes = self._skillComp.GetAllPrefixes()
        if skillPrefixes:
            residents.append(self._BuildResidentMessage(
                f"<available_skills>\n{skillPrefixes}\n</available_skills>",
            ))

        return residents

    def _BuildResidentMessage(self, content: str) -> ContextMessage:
        """创建一条 RESIDENT System 消息。"""
        return ContextMessage.Create(
            chatMessage=ChatMessage(role=ERole.SYSTEM, content=content),
            lodLevel=EContextLodLevel.RESIDENT,
        )

    def _BuildEnvironmentSnapshot(self) -> str:
        """生成环境快照文本块。"""
        lines = [
            "<environment>",
            f"OS: {platform.system()} {platform.release()}",
            "</environment>",
        ]
        return "\n".join(lines)

    # ---- StatusBar 公共接口 ----

    def UpdateTodos(self, todos: list[TodoItem]) -> None:
        """更新 TODO 列表状态（供 TodoWriteTool 写入）。"""
        self._statusBar.UpdateTodos(todos)

    def BuildStatusBar(self, turn: int) -> str:
        """生成当轮状态栏文本，委托 StatusBar 对象生成。

        Args:
            turn: 当前 ReAct 轮次（从 0 起）。
        """
        if turn == 0:
            self._toolComp.ResetCallCounts()

        maxTurns = self._dataComp.config.maxTurns
        callCounts = self._toolComp.GetCallCounts()
        loadedSkillNames = self._skillComp.GetLoadedSkillNames()
        return self._statusBar.Build(turn, maxTurns, callCounts, loadedSkillNames)

    def _ReloadExtensions(self) -> None:
        """从 AgentConfig 指定路径重新加载 extension 注册表。"""
        config = self._dataComp.config

        if config.rulesDir and os.path.isdir(config.rulesDir):
            self._ruleComp.Clear()
            self._ruleComp.LoadFromDirectory(config.rulesDir)

        if config.skillsDir and os.path.isdir(config.skillsDir):
            self._skillComp.Clear()
            self._skillComp.LoadFromDirectory(config.skillsDir)

        if config.mcpJsonPath and os.path.isfile(config.mcpJsonPath):
            self._mcpComp.Clear()
            self._mcpComp.LoadFromMCPJson(config.mcpJsonPath)