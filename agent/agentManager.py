"""AgentManager —— Agent 快捷创建工厂。

封装 LLMManager.GetProvider + Settings.AgentConfig 组装 + Agent 实例化三步流程，
提供一行代码创建 Agent / SimpleAgent 的便捷入口。
"""

from __future__ import annotations

from typing import Optional

from setting import Settings
from llm.baseLLM import BaseLLM
from llm.llmManager import LLMManager

from .agent import Agent
from .simpleAgent import SimpleAgent
from .component.data.agentConfig import AgentConfig


class AgentManager:
    """Agent 快捷创建工厂（静态类）。

    封装 LLM 获取 + Agent 实例化流程，屏蔽 LLMManager 与 AgentConfig 组装细节。
    config 为 None 时自动使用 Settings.AgentConfig() 的默认配置。

    使用方式::

        from agent import AgentManager

        # 用默认模型 + 默认配置创建 ReAct Agent
        agent = AgentManager.CreateAgent()

        # 指定模型名 + 自定义配置
        agent = AgentManager.CreateAgent("deepseek-chat", myConfig)

        # 创建纯对话 SimpleAgent
        simple = AgentManager.CreateSimpleAgent("gpt-4")

        # 用已构造的 BaseLLM 创建
        agent = AgentManager.CreateAgentWithLLM(llm, myConfig)
    """

    @staticmethod
    def CreateAgent(
        modelName: Optional[str] = None,
        config: Optional[AgentConfig] = None,
    ) -> Agent:
        """按模型名创建完整 ReAct Agent。

        Args:
            modelName: 模型名称，为 None 时使用 Settings.defaultModel。
            config: Agent 运行时配置，为 None 时使用 Settings.AgentConfig() 默认配置。

        Returns:
            已初始化的 Agent 实例。
        """
        llm = LLMManager.GetProvider(modelName)
        return Agent(llm, config or Settings.AgentConfig())

    @staticmethod
    def CreateAgentWithLLM(
        llm: BaseLLM,
        config: Optional[AgentConfig] = None,
    ) -> Agent:
        """用已构造的 BaseLLM 创建完整 ReAct Agent。

        Args:
            llm: 已构造的 BaseLLM 实例。
            config: Agent 运行时配置，为 None 时使用 Settings.AgentConfig() 默认配置。

        Returns:
            已初始化的 Agent 实例。
        """
        return Agent(llm, config or Settings.AgentConfig())

    @staticmethod
    def CreateSimpleAgent(
        modelName: Optional[str] = None,
    ) -> SimpleAgent:
        """按模型名创建纯对话 SimpleAgent。

        Args:
            modelName: 模型名称，为 None 时使用 Settings.defaultModel。

        Returns:
            已初始化的 SimpleAgent 实例。
        """
        llm = LLMManager.GetProvider(modelName)
        return SimpleAgent(llm)

    @staticmethod
    def CreateSimpleAgentWithLLM(llm: BaseLLM) -> SimpleAgent:
        """用已构造的 BaseLLM 创建纯对话 SimpleAgent。

        Args:
            llm: 已构造的 BaseLLM 实例。

        Returns:
            已初始化的 SimpleAgent 实例。
        """
        return SimpleAgent(llm)

    @staticmethod
    def CreateSubAgent(modelName: Optional[str] = None) -> Agent:
        """创建工作流子 Agent（禁用 Skill/Rule/MCP）。

        Args:
            modelName: 模型名称，为 None 时使用 Settings.defaultModel。

        Returns:
            已初始化的子 Agent 实例。
        """
        llm = LLMManager.GetProvider(modelName)
        config = AgentConfig(workspaceRoot=Settings.AgentConfig().subAgentDir)
        return Agent(llm, config)
