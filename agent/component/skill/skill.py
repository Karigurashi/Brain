"""Skill 数据对象 —— 封装一个 Agent Skill 的元数据与 SOP 正文。

对标 Claude Code SKILL.md 的渐进式披露架构：
- Layer 1: name + description（~100 tokens），注入 system prompt 作索引。
- Layer 2: body（完整 SOP），通过 Skill 工具按需拉取。
- Layer 3: referenceFiles（引用资源），Skill 执行时再按需加载。
"""

from __future__ import annotations

from typing import Any


class Skill:
    """单个 Agent Skill，包含元数据、工作流指令和引用资源。

    Attributes:
        name: Skill 名称（唯一标识，也是 /skill-name 的调用名）。
        description: 简短描述，用于 Agent 语义匹配。
        body: Skill 正文（SOP 工作流指令），Layer 2 按需加载的内容。
        disableModelInvocation: True 时禁止 Agent 自动调用，仅支持手动 /skill-name。
        allowedTools: 该 Skill 允许使用的工具白名单（空列表表示不限制）。
        model: 指定该 Skill 使用的模型（可选，如 ``"sonnet"``）。
        referenceFiles: 引用资源文件路径列表（Layer 3 按需加载）。
        sourcePath: SKILL.md 文件的来源路径。
    """

    def __init__(
        self,
        name: str,
        description: str = "",
        body: str = "",
        disableModelInvocation: bool = False,
        allowedTools: list[str] | None = None,
        model: str = "",
        referenceFiles: list[str] | None = None,
        sourcePath: str = "",
    ) -> None:
        self.name = name
        self.description = description
        self.body = body
        self.disableModelInvocation = disableModelInvocation
        self.allowedTools = allowedTools or []
        self.model = model
        self.referenceFiles = referenceFiles or []
        self.sourcePath = sourcePath

    # ---- Frontmatter 解析 ----

    @staticmethod
    def FromMarkdown(source: str, sourcePath: str = "") -> "Skill":
        """从带 YAML frontmatter 的 SKILL.md 文本解析 Skill。

        兼容 Claude Code SKILL.md 格式::

            ---
            name: pdf
            description: Process PDF files
            disable-model-invocation: true
            allowed-tools: Read, Bash(git:*)
            model: sonnet
            ---

            ## Goal
            Process PDF files ...

            ## Phase 1: Parse
            ...

        Args:
            source: 带 frontmatter 的 Markdown 全文。
            sourcePath: 文件来源路径。
        """
        meta, body = Skill._ParseFrontmatter(source)

        name = meta.get("name", "")
        description = meta.get("description", "")
        disableModelInvocation = meta.get("disable-model-invocation", False)

        # 兼容 Claude Code 的 allowed-tools 和 Cursor 的 allowedTools
        allowedToolsRaw = meta.get("allowed-tools", meta.get("allowedTools", []))
        if isinstance(allowedToolsRaw, str):
            allowedTools = [t.strip() for t in allowedToolsRaw.split(",") if t.strip()]
        elif isinstance(allowedToolsRaw, list):
            allowedTools = allowedToolsRaw
        else:
            allowedTools = []

        model = meta.get("model", "")

        # 引用文件
        refsRaw = meta.get("references", meta.get("referenceFiles", []))
        if isinstance(refsRaw, str):
            referenceFiles = [r.strip() for r in refsRaw.split(",") if r.strip()]
        elif isinstance(refsRaw, list):
            referenceFiles = refsRaw
        else:
            referenceFiles = []

        return Skill(
            name=name,
            description=description,
            body=body.strip(),
            disableModelInvocation=disableModelInvocation,
            allowedTools=allowedTools,
            model=model,
            referenceFiles=referenceFiles,
            sourcePath=sourcePath,
        )

    # ---- 渐进式披露 ----

    def GetPrefix(self) -> str:
        """Layer 1: 获取轻量前缀（~100 tokens），用于注入 system prompt。"""
        return f"  - {self.name}: {self.description}"

    def GetContent(self) -> str:
        """Layer 2: 获取完整 Skill 正文，用于 Skill 工具返回。

        自动将正文中的相对链接解析为绝对路径，确保 LLM 能通过 Read 工具
        准确定位到引用文件，而非基于 skill 名称猜测路径。
        """
        from agent.core.fileUtils import FileUtils

        resolvedBody = FileUtils.ResolveRelativeLinks(self.body, self.sourcePath)
        return f"<skill name=\"{self.name}\">\n{resolvedBody}\n</skill>"

    def IsAutoInvokable(self) -> bool:
        """Agent 是否可以自动调用此 Skill。

        False 时仅支持手动 ``/skill-name`` 调用。
        """
        return not self.disableModelInvocation

    # ---- 内部方法 ----

    @staticmethod
    def _ParseFrontmatter(source: str) -> tuple[dict[str, Any], str]:
        """解析 YAML frontmatter。

        Returns:
            (meta字典, body字符串)
        """
        import yaml

        source = source.strip()
        if not source.startswith("---"):
            return {}, source

        parts = source.split("---", 2)
        if len(parts) < 3:
            return {}, source

        try:
            meta = yaml.safe_load(parts[1]) or {}
        except Exception:
            meta = {}

        body = parts[2].strip()
        return meta, body