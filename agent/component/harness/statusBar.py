"""StatusBar —— 状态栏对象，封装时间/轮次/工具计数/TODO 进度的生成与状态管理。

HarnessComponent 持有实例，每轮 Build 注入上下文末尾；TodoWriteTool 通过
HarnessComponent 写入 TODO 状态，实现"工具写入 → 状态栏渲染"的职责分离。
"""

from __future__ import annotations

from datetime import datetime, timezone

from .todoItem import TodoItem


class StatusBar:
    """状态栏：管理运行时状态快照与 TODO 列表。

    职责：
    - Build(turn, maxTurns, callCounts) → 生成当轮状态文本
    - UpdateTodos(todos) → 全量替换 TODO 列表
    """

    def __init__(self) -> None:
        self._todos: list[TodoItem] = []
        self._lines: list[str] = []

    # ---- TODO 状态管理 ----

    def UpdateTodos(self, todos: list[TodoItem]) -> None:
        """全量替换 TODO 列表。LLM 每次发送完整快照。"""
        self._todos = todos

    # ---- 状态栏文本生成 ----

    def Build(
        self,
        turn: int,
        maxTurns: int,
        callCounts: dict[str, int],
        loadedSkills: set[str] | None = None,
    ) -> str:
        """生成当轮状态栏文本。

        Args:
            turn: 当前轮次（从 0 起）。
            maxTurns: 最大轮次，-1 表示无限。
            callCounts: {toolName: count} 工具调用计数。
            loadedSkills: 已注册 Skill 名称列表。
        """
        self._lines.clear()
        self._Add("<status>")
        self._AddTime()
        self._AddTurn(turn, maxTurns)
        self._AddTools(callCounts)
        self._AddSkills(loadedSkills or set())
        self._AddTodoProgress()
        self._Add("</status>")
        return "\n".join(self._lines)

    def _Add(self, line: str) -> None:
        """向内部行缓冲追加一行内容。"""
        self._lines.append(line)

    # ---- 状态条目 ----

    def _AddTime(self) -> None:
        now = datetime.now(timezone.utc).astimezone()
        self._Add(f"Time: {now.strftime('%Y-%m-%d %H:%M')}")

    def _AddTurn(self, turn: int, maxTurns: int) -> None:
        label = f"{turn}/{maxTurns}" if maxTurns != -1 else f"{turn}/∞"
        self._Add(f"Turn: {label}")

    def _AddTools(self, callCounts: dict[str, int]) -> None:
        if not callCounts:
            return
        parts = [f"{name}×{count}" for name, count in callCounts.items()]
        total = sum(callCounts.values())
        self._Add(f"Tools: {', '.join(parts)} (total={total})")

    def _AddSkills(self, loadedSkills: set[str]) -> None:
        if not loadedSkills:
            return
        names = ", ".join(loadedSkills)
        self._Add(f"Skills: {names}")

    def _AddTodoProgress(self) -> None:
        if self._todos:
            self._Add("TODO:")
            for i, t in enumerate(self._todos, 1):
                self._Add(f"  [{i}] {t.content} ({t.status.value})")
