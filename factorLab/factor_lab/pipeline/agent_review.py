"""
Pipeline Stage 7: AgentReview
=============================
离线 Agent 分析模块 —— 回测完成后自动生成审查报告。

用法:
    reviewer = AgentReview(model_name="deepseek-high")
    report = reviewer.review(pipeline_result)

与现有 Agent 系统集成:
    使用 AgentManager.CreateSimpleAgent() 创建非 ReAct 对话 Agent，
    注入 SystemPrompt + Pipeline 全量结果，获取结构化分析报告。

依赖:
    agent (项目根级 Agent 框架)
"""

from __future__ import annotations

import asyncio
import json
from typing import Optional
from dataclasses import dataclass


@dataclass
class ReviewReport:
    """Agent 审查报告"""
    # ── 总体评价 ──
    overall_rating: str = ""            # "优秀" / "良好" / "一般" / "存疑"
    overall_score: float = 0.0          # 1-10

    # ── 分项分析 ──
    regime_quality: str = ""            # Regime 划分质量评价
    factor_quality: str = ""            # 因子质量评价
    backtest_quality: str = ""          # 回测可靠性评价
    risk_warnings: str = ""             # 风险提示

    # ── 改进建议 ──
    suggestions: str = ""
    next_search_directions: str = ""    # 下一轮因子搜索方向

    # ── 原始输出 ──
    raw_response: str = ""


class AgentReview:
    """
    Agent 离线审查器。

    集成项目现有 Agent 框架（agent.AgentManager），
    在 Pipeline 全部运行完成后，将结果打包为结构化 Prompt，
    调用本地 LLM 生成审查报告。

    Example:
        reviewer = AgentReview(model_name="deepseek-high")
        report = reviewer.review(result)
        print(report.suggestions)
    """

    def __init__(
        self,
        model_name: Optional[str] = None,
        temperature: float = 0.3,
        verbose: bool = True,
    ):
        """
        Args:
            model_name: Agent 模型名，None 则用系统默认
            temperature: 采样温度（分析任务建议低温度）
            verbose: 打印分析过程
        """
        self.model_name = model_name
        self.temperature = temperature
        self.verbose = verbose

    # ── 公开入口 ──

    def review(self, pipeline_result) -> ReviewReport:
        """
        审查 Pipeline 完整结果。

        Args:
            pipeline_result: PipelineResult 实例

        Returns:
            ReviewReport
        """
        if self.verbose:
            print(f"\n{'='*65}")
            print(f"  Stage 7: Agent 离线审查")
            print(f"{'='*65}")

        # 1. 构建 Prompt
        system_prompt = self._build_system_prompt()
        user_message = self._build_user_message(pipeline_result)

        if self.verbose:
            print(f"  [Agent] 发送审查请求 ({len(user_message)} 字符)...")

        # 2. 调用 Agent
        try:
            raw = asyncio.run(self._call_agent(system_prompt, user_message))
        except Exception as e:
            raw = f"[Agent 调用失败: {e}]"

        # 3. 解析
        report = self._parse_response(raw)

        if self.verbose:
            self._print_report(report)

        return report

    # ── Agent 调用 ──

    async def _call_agent(
        self,
        system_prompt: str,
        user_message: str,
    ) -> str:
        """调用项目 Agent 框架"""
        import sys
        import os

        # 确保 agent 模块在 sys.path 中
        # __file__ = .../Mango/factorLab/factor_lab/pipeline/agent_review.py
        # 往上 3 层 → .../Mango
        mango_root = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "..", "..")
        )
        if mango_root not in sys.path:
            sys.path.insert(0, mango_root)

        # Agent 框架需要从 Mango 根目录运行（读取 workspace/settings.json）
        _cwd = os.getcwd()
        os.chdir(mango_root)

        try:
            from agent.agentManager import AgentManager
            from agent.component.eventBus.agentStreamEvent import (
                AgentStreamEvent, EAgentStreamEventType,
            )
            from agent.component.eventBus.eventBusComponent import EventBusComponent
            from agent.component.llm.llmComponent import LLMComponent

            # 创建 SimpleAgent（纯对话，不需要工具/ReAct）
            agent = AgentManager.CreateSimpleAgent(self.model_name)

            # 设置温度
            llm_comp = agent.GetComponent(LLMComponent)
            llm_comp.RequestParams.temperature = self.temperature

            # 收集完整回复
            full_content: list[str] = []

            def on_event(event: AgentStreamEvent):
                if event.eventType == EAgentStreamEventType.TEXT_COMPLETE:
                    full_content.append(event.content)

            agent.GetComponent(EventBusComponent).AddListener(on_event)

            # 运行
            agent.SetSystemPrompt(system_prompt)
            await agent.RunAsync(
                userMessage=user_message,
                stream=True,
            )

            result = "\n".join(full_content) if full_content else ""
            # 清除 GBK 无法编码的字符
            result = result.encode('gbk', errors='replace').decode('gbk')
            return result

        finally:
            os.chdir(_cwd)

    # ── Prompt 构建 ──

    @staticmethod
    def _build_system_prompt() -> str:
        return """你是一位资深量化研究员，负责审查自动化因子挖掘 Pipeline 的输出结果。

你的任务：
1. 评估 Regime（市场状态）划分是否合理
2. 评估挖掘出的因子质量（IC 是否可靠、是否可能过拟合）
3. 评估回测结果的可信度（收益是否来自少数异常交易、是否有幸存者偏差）
4. 识别潜在风险（因子拥挤、风格暴露、参数过拟合）
5. 给出下一轮因子搜索的具体方向建议

审查原则：
- 对回测数字保持怀疑——高收益 + 低回撤往往是过拟合信号
- IC 在训练/验证/测试三段的走势比绝对值更重要
- 关注收益集中度：如果少数几笔交易贡献了大部分利润，策略不可靠
- 不同 Regime 应该产出不同类型的因子，如果所有 Regime 的最优因子都是同一类型，说明 Regime 划分无效

请用中文回复，结构清晰。"""

    def _build_user_message(self, result) -> str:
        """将 PipelineResult 格式化为结构化 Prompt"""
        parts = []

        # ── 基本信息 ──
        parts.append(f"## 股票: {result.stock_code}")
        parts.append(f"## Pipeline 耗时: {result.elapsed_seconds:.1f}s")
        parts.append(f"## 完成阶段: {' → '.join(result.stages_completed)}")

        # ── Stage 2: 数据拆分 ──
        sr = result.split_result
        if sr:
            parts.append(f"\n## 数据拆分")
            parts.append(f"- 总样本: {sr.n_total} 天")
            parts.append(f"- 训练: {sr.n_train} 天 ({sr.train_start} → {sr.train_end})")
            parts.append(f"- 验证: {sr.n_val} 天 ({sr.val_start} → {sr.val_end})")
            parts.append(f"- 测试: {sr.n_test} 天 ({sr.test_start} → {sr.test_end})")

        # ── Stage 3: Regime ──
        rr = result.regime_result
        if rr:
            parts.append(f"\n## Regime 划分 ({rr.n_regimes} 个)")
            for ri in range(rr.n_regimes):
                s = rr.regime_stats.get(ri, {})
                parts.append(
                    f"  Regime {ri}: "
                    f"train={s.get('n_train',0)}天 "
                    f"val={s.get('n_val',0)}天 "
                    f"test={s.get('n_test',0)}天 "
                    f"mean_ret_train={s.get('mean_target_train',0):+.4f} "
                    f"mean_ret_val={s.get('mean_target_val',0):+.4f} "
                    f"mean_ret_test={s.get('mean_target_test',0):+.4f}"
                )

        # ── Stage 4: 因子挖掘 ──
        mr = result.mine_result
        if mr:
            parts.append(f"\n## 因子挖掘 ({mr.n_total_factors} 个因子, {mr.n_regimes_processed} 个 Regime)")
            for ri, factors in mr.all_factors.items():
                if not factors:
                    continue
                parts.append(f"\n### Regime {ri} (共 {len(factors)} 个因子):")
                for f in factors[:5]:
                    parts.append(
                        f"  - {f.name} | cat={f.category} | "
                        f"train_IC={f.train_ic:+.4f} | "
                        f"score={f.score:.4f}"
                    )
                    if f.expression:
                        expr_short = f.expression[:80]
                        parts.append(f"    公式: {expr_short}")

        # ── Stage 5: 验证 ──
        vr = result.validation_result
        if vr:
            parts.append(f"\n## 因子验证: +{vr.n_passed} passed  -{vr.n_rejected} rejected")
            for ri, factors in vr.passed.items():
                if not factors:
                    continue
                parts.append(f"\n### Regime {ri} (通过 {len(factors)} 个):")
                for f in factors:
                    parts.append(
                        f"  - {f.name} | cat={f.category} | "
                        f"train_IC={f.train_ic:+.4f} | "
                        f"test_IC={f.test_ic:+.4f}"
                    )

        # ── Stage 6: 回测 ──
        br = result.backtest_result
        if br:
            parts.append(f"\n## 样本外回测 (Regime 自适应)")
            parts.append(f"- 总收益: {br.total_return:+.2%}")
            parts.append(f"- 年化收益: {br.annual_return:+.2%}")
            parts.append(f"- Sharpe: {br.sharpe_ratio:.2f}")
            parts.append(f"- 最大回撤: {br.max_drawdown:+.2%}")
            parts.append(f"- 交易笔数: {br.n_trades} (做多 {br.n_long})")
            parts.append(f"- 胜率: {br.win_rate:.1%}")
            parts.append(f"- Buy & Hold: {br.buy_and_hold_return:+.2%}")
            parts.append(f"\n### Per-Regime 表现:")
            for ri, perf in sorted(br.regime_performance.items()):
                parts.append(
                    f"  Regime {ri}: {perf['n_trades']}笔 "
                    f"收益={perf['total_return']:+.2%} "
                    f"胜率={perf['win_rate']:.1%}"
                )

            if br.baseline_result:
                bl = br.baseline_result
                delta = br.total_return - bl["total_return"]
                parts.append(f"\n### vs 无Regime切换基准:")
                parts.append(f"- 基准收益: {bl['total_return']:+.2%}")
                parts.append(f"- Regime切换超额: {delta:+.2%}")

        # ── 交易明细摘要 ──
        if br and br.trades_df is not None:
            tdf = br.trades_df
            if len(tdf) > 0:
                returns = tdf["return"].values
                top3_idx = returns.argsort()[-3:][::-1]
                bottom3_idx = returns.argsort()[:3]

                parts.append(f"\n## 最佳3笔交易:")
                for idx in top3_idx:
                    row = tdf.iloc[idx]
                    parts.append(f"  {row['date']} regime={int(row['regime'])} "
                                 f"ret={row['return']:+.2%}")

                parts.append(f"\n## 最差3笔交易:")
                for idx in bottom3_idx:
                    row = tdf.iloc[idx]
                    parts.append(f"  {row['date']} regime={int(row['regime'])} "
                                 f"ret={row['return']:+.2%}")

                # 收益集中度
                top5_pct = returns[returns.argsort()[-5:][::-1]].sum() / returns.sum() * 100
                parts.append(f"\n## 收益集中度:")
                parts.append(f"- Top-5 交易贡献: {top5_pct:.1f}% (越高越不可靠)")

        # ── 错误 ──
        if result.errors:
            parts.append(f"\n## 运行错误:")
            for stage, err in result.errors:
                parts.append(f"  [{stage}] {err}")

        # ── 审查要求 ──
        parts.append(f"""
---
请从以下维度输出审查报告（简洁直接）：

1. **Regime 划分评价**（1-2句）
2. **因子质量评价**（每个 Regime 1句，指出最好/最差的因子）
3. **回测可信度**（1-2句，关注收益集中度/IC衰减/样本外表现）
4. **风险警告**（1-2句，过拟合信号/市场环境变化风险）
5. **下一轮建议**（2-3个具体搜索方向，如"增加波动率因子"或"缩短预测周期到5天"）
""")

        return "\n".join(parts)

    # ── 解析 ──

    @staticmethod
    def _parse_response(raw: str) -> ReviewReport:
        """从 LLM 回复中提取结构化字段"""
        report = ReviewReport(raw_response=raw)

        # 简单关键词提取
        if "优秀" in raw or "excellent" in raw.lower():
            report.overall_rating = "优秀"
        elif "良好" in raw or "good" in raw.lower():
            report.overall_rating = "良好"
        elif "存疑" in raw or "可疑" in raw or "过拟合" in raw:
            report.overall_rating = "存疑"
        else:
            report.overall_rating = "一般"

        # 提取各段内容
        sections = {
            "regime_quality": ["Regime", "状态划分", "市场状态"],
            "factor_quality": ["因子质量", "因子评价"],
            "backtest_quality": ["回测", "可信度", "可靠性"],
            "risk_warnings": ["风险", "警告", "过拟合"],
            "suggestions": ["建议", "下一轮", "搜索方向"],
        }

        lines = raw.split("\n")
        for field, keywords in sections.items():
            captured = []
            in_section = False
            for line in lines:
                if any(kw in line for kw in keywords) and len(line) < 30:
                    in_section = True
                    continue
                if in_section and line.strip().startswith(("1.", "2.", "3.", "4.", "5.", "-", "*")):
                    captured.append(line.strip())
                elif in_section and line.strip() == "":
                    in_section = False
            setattr(report, field, "\n".join(captured) if captured else raw[:300])

        return report

    def _print_report(self, report: ReviewReport):
        """打印审查报告"""
        print(f"\n{'─'*55}")
        print(f"  Agent 审查报告")
        print(f"{'─'*55}")
        if report.overall_rating:
            print(f"  总体评级: {report.overall_rating}")

        if report.regime_quality:
            print(f"\n  [Regime 评价] {report.regime_quality[:200]}")
        if report.factor_quality:
            print(f"\n  [因子评价] {report.factor_quality[:200]}")
        if report.backtest_quality:
            print(f"\n  [回测可信度] {report.backtest_quality[:200]}")
        if report.risk_warnings:
            print(f"\n  [风险] {report.risk_warnings[:200]}")
        if report.suggestions:
            print(f"\n  [建议]")
            for line in report.suggestions.split("\n")[:5]:
                print(f"    {line}")
        print(f"\n  ── 原始回复 ({len(report.raw_response)} 字符) ──")
        print(f"  {report.raw_response[:400]}...")
        print(f"{'─'*55}")
