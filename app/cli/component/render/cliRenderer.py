"""CliRenderer —— 事件→终端实时渲染引擎。

订阅 EventBusComponent 的 AgentStreamEvent 流，将 10 种事件类型
映射为 ANSI 格式终端输出。使用 sys.stdout.write()+flush 精细控制，
感知事件对象池生命周期（不持有 event 引用）。

视觉设计对标 Claude Code CLI：紫色主色调、左边界缩进、菱形工具标识。
"""

from __future__ import annotations

import json
import sys

from agent.component.eventBus.agentStreamEvent import AgentStreamEvent, EAgentStreamEventType

from ...cliConfig import CliConfig


class CliRenderer:
    """事件→终端实时渲染器。

    OnEvent 回调由 EventBusComponent.Push 同步调用，
    Push 返回后 event 被归还对象池，因此 OnEvent MUST NOT
    持有 event 引用。所有数据在回调内立即提取并输出。
    """

    def __init__(self, config: CliConfig) -> None:
        self._config = config
        self._inThinking = False
        self._inText = False
        self._turnCount = 0
        self._textLineBuffer = ""
        self._inCodeBlock = False

    # ---- 事件分发入口 ----

    def OnEvent(self, event: AgentStreamEvent) -> None:
        """EventBusComponent 回调入口，按事件类型分发。"""
        et = event.eventType
        if et == EAgentStreamEventType.START:
            self._OnStart(event)
        elif et == EAgentStreamEventType.TURN_START:
            self._OnTurnStart(event)
        elif et == EAgentStreamEventType.THINKING_DELTA:
            self._OnThinkingDelta(event)
        elif et == EAgentStreamEventType.THINKING_COMPLETE:
            self._OnThinkingComplete(event)
        elif et == EAgentStreamEventType.TEXT_DELTA:
            self._OnTextDelta(event)
        elif et == EAgentStreamEventType.TEXT_COMPLETE:
            self._OnTextComplete(event)
        elif et == EAgentStreamEventType.TOOL_START:
            self._OnToolStart(event)
        elif et == EAgentStreamEventType.TOOL_RESULT:
            self._OnToolResult(event)
        elif et == EAgentStreamEventType.COMPACTION:
            self._OnCompaction(event)
        elif et == EAgentStreamEventType.ERROR:
            self._OnError(event)
        elif et == EAgentStreamEventType.DONE:
            self._OnDone(event)

    # ---- Turn ----

    def _OnStart(self, event: AgentStreamEvent) -> None:
        """RunAsync 入口，重置所有渲染状态。"""
        self._EndCurrentMode()
        self._inThinking = False
        self._inText = False
        self._inCodeBlock = False
        self._textLineBuffer = ""
        self._turnCount = 0

    def _OnTurnStart(self, event: AgentStreamEvent) -> None:
        """推理轮次开始，首轮静默，后续轮打印分隔线。"""
        self._inThinking = False
        self._inText = False
        self._inCodeBlock = False
        self._textLineBuffer = ""
        if self._turnCount > 0:
            self._WriteLine("")
        self._turnCount += 1

    # ---- Thinking ----

    def _OnThinkingDelta(self, event: AgentStreamEvent) -> None:
        """思考增量 —— 紫色左边栏 + 灰色内容。"""
        if not self._config.showThinking:
            return
        self._EnsureThinkingMode()
        self._Write(self._config.Color(event.content, self._config.GRAY))

    def _OnThinkingComplete(self, event: AgentStreamEvent) -> None:
        """思考阶段完成，输出换行闭合。"""
        if not self._config.showThinking:
            return
        if self._inThinking:
            self._Write("\n")
        self._inThinking = False

    # ---- Text ----

    def _OnTextDelta(self, event: AgentStreamEvent) -> None:
        """文本增量 —— 按行缓冲，完整行通过 RenderMdLine 转换后输出。"""
        self._EnsureTextMode()
        self._textLineBuffer += event.content
        # 处理所有完整行
        while '\n' in self._textLineBuffer:
            idx = self._textLineBuffer.index('\n')
            line = self._textLineBuffer[:idx]
            self._textLineBuffer = self._textLineBuffer[idx + 1:]
            rendered, self._inCodeBlock = self._config.RenderMdLine(line, self._inCodeBlock)
            if rendered:
                self._WriteLine(rendered)

    def _OnTextComplete(self, event: AgentStreamEvent) -> None:
        """文本阶段完成 —— 刷出缓冲区剩余内容。

        不在此处关闭文本模式，由后续 _OnToolStart / _OnDone 中的
        _EndCurrentMode() 统一处理换行与状态重置，避免重复换行。
        """
        self._FlushTextBuffer()

    # ---- Tool ----

    def _OnToolStart(self, event: AgentStreamEvent) -> None:
        """工具调用开始 —— 菱形图标 + Cyan 工具名 + 参数。"""
        self._FlushTextBuffer()
        self._EndCurrentMode()
        args = event.toolArgs or {}
        argsStr = json.dumps(args, ensure_ascii=False)
        if len(argsStr) > self._config.maxToolArgsDisplay:
            argsStr = argsStr[:self._config.maxToolArgsDisplay] + "..."
        c = self._config
        line = (
            f"{c.Purple(c.BOX_V)} "
            f"{c.Color(c.ICON_TOOL, c.CYAN_BRIGHT)} "
            f"{c.Bold(event.toolName)}"
            f"{c.Dim(f'({argsStr})')}"
        )
        self._WriteLine(line)

    def _OnToolResult(self, event: AgentStreamEvent) -> None:
        """工具结果渲染 —— 错误红色左边栏，正常灰色。"""
        isError = event.toolResult is not None and not event.toolResult.success
        c = self._config
        borderColor = c.RED if isError else c.GRAY
        prefix = f"{c.Color(c.BOX_V, borderColor)} "
        chunkColor = c.RED if isError else c.GRAY

        content = event.content
        if len(content) > c.maxToolResultChars:
            content = content[:c.maxToolResultChars] + "..."
        truncated = c.TruncateLines(content, c.maxToolResultLines)
        for line in truncated.split('\n'):
            self._WriteLine(f"{prefix}{c.Color(line, chunkColor)}")

    # ---- Compaction / Error / Done ----

    def _OnCompaction(self, event: AgentStreamEvent) -> None:
        """上下文压缩通知。"""
        self._FlushTextBuffer()
        self._EndCurrentMode()
        c = self._config
        content = event.content or f"Freed {event.tokenSaved} tokens, {event.compactedCount} messages affected"
        self._WriteLine(
            f"{c.Color(c.ICON_COMPACTION, c.AMBER)} {c.Dim(content)}"
        )

    def _OnError(self, event: AgentStreamEvent) -> None:
        """错误事件 —— 红色左边栏。"""
        self._FlushTextBuffer()
        self._EndCurrentMode()
        c = self._config
        self._WriteLine(
            f"{c.Color(c.BOX_V, c.RED)} {c.Color(c.ICON_ERROR, c.RED)} {c.Color(event.error or 'Unknown error', c.RED)}"
        )

    def _OnDone(self, event: AgentStreamEvent) -> None:
        """本轮结束，重置模式与轮次。"""
        self._EndCurrentMode()
        self._Write("\n")
        self._turnCount = 0

    # ---- 模式管理 ----

    def _EnsureThinkingMode(self) -> None:
        """确保进入思考输出模式 —— 紫色左边栏 + 标签。"""
        if self._inThinking:
            return
        self._EndCurrentMode()
        c = self._config
        self._Write(f"{c.Purple(c.BOX_V)} {c.Purple('Thought')} ")
        self._inThinking = True

    def _EnsureTextMode(self) -> None:
        """确保进入文本输出模式。"""
        if self._inText:
            return
        self._EndCurrentMode()
        self._inText = True

    def _EndCurrentMode(self) -> None:
        """结束当前模式（thinking 或 text）。"""
        if self._inThinking:
            self._inThinking = False
            self._Write("\n")
        elif self._inText:
            self._inText = False
            self._Write("\n")

    def _FlushTextBuffer(self) -> None:
        """刷出 _textLineBuffer 中尚未遇到换行符的残留内容。"""
        if self._textLineBuffer:
            rendered, self._inCodeBlock = self._config.RenderMdLine(self._textLineBuffer, self._inCodeBlock)
            if rendered:
                self._WriteLine(rendered)
            self._textLineBuffer = ""

    # ---- 公开输出方法（供 CliContext / 组件直接打印） ----

    def PrintInfo(self, text: str) -> None:
        """打印信息行 —— 青色图标。"""
        c = self._config
        self._WriteLine(f"{c.Color(c.ICON_INFO, c.CYAN_BRIGHT)} {text}")

    def PrintWarning(self, text: str) -> None:
        """打印警告行 —— 琥珀色。"""
        c = self._config
        self._WriteLine(f"{c.Color(c.ICON_INFO, c.AMBER)} {c.Color(text, c.AMBER)}")

    def PrintError(self, text: str) -> None:
        """打印错误行 —— 红色图标 + 红色文本。"""
        c = self._config
        self._WriteLine(f"{c.Color(c.ICON_ERROR, c.RED)} {c.Color(text, c.RED)}")

    def PrintDim(self, text: str) -> None:
        """打印 dim 行。"""
        self._WriteLine(self._config.Dim(text))

    def PrintBanner(self, modelName: str, groupName: str) -> None:
        """打印欢迎横幅。"""
        self._WriteLine(self._config.RenderBanner(modelName, groupName))
        self._WriteLine("")

    def PrintFooter(self, modelName: str, promptTokens: int, completionTokens: int, cacheHitRate: float) -> None:
        """打印本轮用量页脚。

        Args:
            modelName: 模型名。
            promptTokens: 输入 token。
            completionTokens: 输出 token。
            cacheHitRate: 缓存命中率 (0-100)。
        """
        c = self._config
        parts = [
            f"{c.Dim('in')} {c.Bold(c.FormatK(promptTokens))}",
            f"{c.Dim('out')} {c.Bold(c.FormatK(completionTokens))}",
        ]
        if cacheHitRate > 0:
            parts.append(f"{c.Dim('cache')} {c.Color(f'{cacheHitRate:.1f}%', c.AMBER)}")
        tokenStr = "  ".join(parts)
        footer = f"{c.Dim(modelName)}  {tokenStr}"
        self._WriteLine(f"  {c.Dim('─' * 50)}")
        self._WriteLine(f"  {footer}")
        self._WriteLine("")

    # ---- 底层输出 ----

    @staticmethod
    def _Write(text: str) -> None:
        """写入终端并立即 flush，保证实时性。"""
        sys.stdout.write(text)
        sys.stdout.flush()

    @staticmethod
    def _WriteLine(text: str) -> None:
        """写入一行并 flush。"""
        sys.stdout.write(text + "\n")
        sys.stdout.flush()
