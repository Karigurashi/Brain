"""Skill 文件加载器 —— 递归扫描目录中的 SKILL.md 文件并解析为 Skill 对象。

负责文件系统层的解析，与 SkillComponent 的运行时管理解耦。
"""

from __future__ import annotations

import os
from pathlib import Path

from common.logger import Logger

from .skill import Skill


class SkillLoader:
    """从文件系统加载 SKILL.md 文件的扫描器。

    递归扫描 skills 目录，解析 frontmatter 和正文，生成 Skill 对象。
    对标 Claude Code 的 .claude/skills/ 目录结构和 Skill 发现机制。

    用法::

        loader = SkillLoader()
        count = loader.ScanDirectory(".claude/skills")
        skills = loader.GetAllSkills()
        for skill in skills.values():
            print(skill.GetPrefix())
    """

    def __init__(self) -> None:
        self._skills: dict[str, Skill] = {}

    # ---- 扫描 ----

    def ScanDirectory(self, directory: str) -> int:
        """递归扫描目录，加载所有 SKILL.md 文件。

        目录名作为默认 Skill 名称（当 SKILL.md 中未指定时）。

        Args:
            directory: skills 根目录路径。

        Returns:
            成功加载的 Skill 数量。
        """
        count = 0
        dirPath = Path(directory)
        if not dirPath.is_dir():
            return count

        for skillFile in sorted(dirPath.rglob("SKILL.md")):
            try:
                skill = self._LoadSkillFile(skillFile)
                if not skill.name:
                    # 用父目录名作为回退名称
                    skill.name = skillFile.parent.name
                self._skills[skill.name] = skill
                count += 1
            except Exception as exc:
                Logger.Warning(f"SkillLoader: failed to load {skillFile}: {exc}")
                continue

        return count

    def LoadSingleFile(self, filePath: str) -> Skill | None:
        """加载单个 SKILL.md 文件。

        Args:
            filePath: SKILL.md 文件的绝对或相对路径。

        Returns:
            解析后的 Skill 对象，失败返回 None。
        """
        try:
            skill = self._LoadSkillFile(Path(filePath))
            if not skill.name:
                skill.name = Path(filePath).parent.name
            self._skills[skill.name] = skill
            return skill
        except Exception as exc:
            Logger.Warning(f"SkillLoader: failed to load single file {filePath}: {exc}")
            return None

    # ---- 查询 ----

    def GetAllSkills(self) -> dict[str, Skill]:
        """获取所有已加载的 Skill。"""
        return dict(self._skills)

    def GetSkill(self, name: str) -> Skill | None:
        """按名称获取 Skill。"""
        return self._skills.get(name)

    def GetDescriptions(self) -> str:
        """Layer 1: 获取所有 Skill 的 name + description 清单。

        用于注入 system prompt，每条约 100 tokens。
        """
        if not self._skills:
            return "No skills available."
        lines = [skill.GetPrefix() for skill in self._skills.values()]
        return "\n".join(lines)

    def GetContent(self, name: str) -> str:
        """Layer 2: 获取指定 Skill 的完整正文。

        用于 Skill 工具返回，对标 Claude Code 的 roleMessage 注入。

        Args:
            name: Skill 名称。

        Returns:
            Skill 的完整 SOP 正文，找不到时返回错误信息。
        """
        skill = self._skills.get(name)
        if not skill:
            return f"Error: Unknown skill '{name}'. Available: {', '.join(sorted(self._skills.keys()))}"
        return skill.GetContent()

    # ---- 管理 ----

    def Count(self) -> int:
        """已加载 Skill 总数。"""
        return len(self._skills)

    def Clear(self) -> None:
        """清空所有已加载的 Skill。"""
        self._skills.clear()

    # ---- 内部方法 ----

    @staticmethod
    def _LoadSkillFile(filePath: Path) -> Skill:
        """读取并解析单个 SKILL.md 文件。"""
        source = filePath.read_text(encoding="utf-8")
        skill = Skill.FromMarkdown(source, sourcePath=str(filePath))
        return skill