"""RuleComponent —— 将 rulesDir 下的 .md 文件内容注入 Context。

挂载到 BaseAgent 后，通过 BaseAgent.GetComponent(RuleComponent) 获取。
GetAlwaysApplyBody() 每次都直接从 rulesDir 实时读取 .md 文件并合并注入 System Prompt，
自动将正文中的相对链接解析为绝对路径。
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from agent.core.baseComponent import BaseComponent
from common.logger import Logger

if TYPE_CHECKING:
    from agent.core.baseAgent import BaseAgent


class RuleComponent(BaseComponent):
    """Rule 管理组件 —— 直接加载文件夹下的 .md/.mdc 文件全部注入。

    用法::

        agent = BaseAgent()
        ruleComp = RuleComponent()
        agent.AddComponent(ruleComp)
        ruleComp.LoadFromDirectory("workspace/rules")
    """

    def __init__(self) -> None:
        self._entries: list[str] = []

    # ---- 生命周期 ----

    def OnInitialize(self, agent: BaseAgent) -> None:
        """挂载后初始化。"""
        pass

    def OnDestroy(self) -> None:
        """从 BaseAgent 卸载时回调。"""
        self._entries.clear()

    # ---- Context 注入 ----

    def GetAlwaysApplyBody(self) -> str:
        """获取已加载规则的合并正文，用于注入 Context。"""
        return "\n\n".join(self._entries)

    # ---- 加载 ----

    def LoadFromDirectory(self, directory: str) -> None:
        """直接从目录读取所有 .md 文件，存入 _entries。

        GetAlwaysApplyBody() 返回已加载内容的合并结果。
        """
        from agent.core.fileUtils import FileUtils

        self._entries.clear()

        if not os.path.isdir(directory):
            return

        for root, _dirs, files in os.walk(directory):
            for filename in files:
                if not filename.endswith(".md"):
                    continue
                filePath = os.path.join(root, filename)
                try:
                    with open(filePath, "r", encoding="utf-8") as f:
                        body = f.read()
                    if body.strip():
                        self._entries.append(FileUtils.ResolveRelativeLinks(body, filePath))
                except Exception as exc:
                    Logger.Warning(f"RuleComponent: failed to read rule from {filePath}: {exc}")
                    continue

    # ---- 管理 ---

    def Clear(self) -> None:
        """清空已加载规则。"""
        self._entries.clear()
