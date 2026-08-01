"""
Pipeline Stage 5.5: FactorAnalyzer
==================================
因子质量分析 —— 用交易模拟替代IC分析，和实盘同一标准。

核心理念:
  不再算 Spearman IC（和实盘信号不对齐），而是直接用交易模拟评估：
  1. Trading Sim on Train — 在训练集内做 Walk-Forward 交易模拟
  2. Trading Sim on Val   — 在验证集上用同样参数模拟
  3. Consistency Check    — Train赚钱+Val赚钱 → PASS

用法:
    from factor_lab.pipeline.factor_analyzer import FactorAnalyzer
    analyzer = FactorAnalyzer()
    report = analyzer.analyze(validated_factors, features, close, split_result)
"""

from __future__ import annotations

import numpy as np
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field


@dataclass
class TradingSimResult:
    """单因子交易模拟结果"""
    factor_name: str
    train_total_ret: float = 0.0     # Train子集模拟收益
    train_sharpe: float = 0.0
    train_n_trades: int = 0
    val_total_ret: float = 0.0       # Val模拟收益
    val_sharpe: float = 0.0
    val_n_trades: int = 0
    consistency: str = "UNKNOWN"     # CONSISTENT / OVERFIT / DEAD
    verdict: str = "FAIL"


@dataclass
class FactorAnalysisReport:
    """因子综合分析报告 — 基于交易模拟"""
    trading_sim_results: Dict[str, TradingSimResult] = field(default_factory=dict)
    final_verdicts: Dict[str, str] = field(default_factory=dict)
    best_factor: str = ""
    best_horizon: int = 5
    analysis_summary: str = ""


# ================================================================
# FactorAnalyzer
# ================================================================

class FactorAnalyzer:
    """
    因子深度分析器。

    对每个通过验证的因子:
      1. IC Decay: 计算 [1,3,5,10,20] 天 IC，拟合指数衰减，找最优周期
      2. Walk-Forward: N 个滚动窗口验证 IC 稳定性
      3. Stratified: 因子值五分位，检验单调性

    Example:
        analyzer = FactorAnalyzer(n_walk_forward_windows=5)
        report = analyzer.analyze(
            factors=validation_result.passed,
            features=features,
            close=close,
            split_result=split_result,
        )
    """

    def __init__(
        self,
        ic_horizons: List[int] = None,
        n_walk_forward_windows: int = 5,
        wf_train_pct: float = 0.60,
        wf_purge_days: int = 10,
        n_quintiles: int = 5,
        min_samples_per_bin: int = 5,
        verbose: bool = True,
    ):
        """
        Args:
            ic_horizons: IC 衰减分析周期列表
            n_walk_forward_windows: Walk-Forward 窗口数
            wf_train_pct: 每窗口训练占比
            wf_purge_days: 训练/验证间隔（防止自相关泄露）
            n_quintiles: 分层回测分组数
            min_samples_per_bin: 每组最少样本
            verbose: 打印进度
        """
        self.ic_horizons = ic_horizons or [1, 3, 5, 10]
        self.n_wf_windows = n_walk_forward_windows
        self.wf_train_pct = wf_train_pct
        self.wf_purge_days = wf_purge_days
        self.n_quintiles = n_quintiles
        self.min_samples_per_bin = min_samples_per_bin
        self.verbose = verbose

    # ==================================================================
    # 公开入口
    # ==================================================================

    def analyze(
        self,
        factors: Dict[int, List],
        features: Dict[str, np.ndarray],
        close: np.ndarray,
        split_result,
    ) -> FactorAnalysisReport:
        """
        用交易模拟替代IC分析。每个因子在 Train 和 Val 上各跑一次
        迷你回测（滚动分位数+标准参数），判断一致性。
        """
        from factor_lab.pipeline.daily_backtester import (
            DailyBacktester, build_rolling_signal
        )
        from factor_lab.operators import spearman_correlation

        if self.verbose:
            print(f"\n{'='*60}")
            print(f"  Stage 6: Factor Trading Simulation Analysis")
            print(f"{'='*60}")

        report = FactorAnalysisReport()

        # 展开所有因子
        all_factors = []
        for ri, flist in factors.items():
            for f in flist:
                all_factors.append((ri, f))

        if not all_factors:
            return report

        # 用索引做日期（回测只用于日志，不影响计算）
        dummy_dates = [str(i) for i in range(len(close))]
        train_mask = split_result.train_mask
        val_mask = split_result.val_mask

        # 标准参数（不做优化，看原始质量）
        std_entry, std_exit, std_mh, std_sl = 0.70, 0.35, 5, -0.10

        for ri, factor in all_factors:
            fv = factor.factor_values
            if fv is None or len(fv) < 30:
                continue

            name = f"{factor.name}_R{ri}"

            # 计算 Train IC（定方向用）
            fwd5 = np.full(len(close), np.nan)
            fwd5[:-5] = close[5:] / close[:-5] - 1.0
            tv = train_mask & np.isfinite(fv) & np.isfinite(fwd5)
            train_ic = spearman_correlation(fv[tv], fwd5[tv]) if tv.sum() > 15 else 0.0

            # 构建滚动分位数信号
            sig = build_rolling_signal(fv, train_ic, lookback=20)

            # ── Train 内部 Walk-Forward 交易模拟 ──
            train_indices = np.where(train_mask)[0]
            if len(train_indices) >= 60:
                # 用 Train 的后 1/3 作为子验证集
                split_pt = len(train_indices) * 2 // 3
                sub_train = np.zeros(len(close), dtype=bool)
                sub_train[train_indices[:split_pt]] = True
                sub_val = np.zeros(len(close), dtype=bool)
                sub_val[train_indices[split_pt:]] = True

                bt = DailyBacktester(std_entry, std_exit, std_mh, std_sl, verbose=False)
                r = bt.run(sig, close, dummy_dates, sub_val)
                train_ret = r.total_return
                train_sharpe = r.sharpe_ratio
                train_nt = r.n_trades
            else:
                train_ret, train_sharpe, train_nt = 0, 0, 0

            # ── Val 交易模拟 ──
            val_mask_use = val_mask
            if val_mask_use.sum() >= 20:
                bt2 = DailyBacktester(std_entry, std_exit, std_mh, std_sl, verbose=False)
                r2 = bt2.run(sig, close, dummy_dates, val_mask_use)
                val_ret = r2.total_return
                val_sharpe = r2.sharpe_ratio
                val_nt = r2.n_trades
            else:
                val_ret, val_sharpe, val_nt = 0, 0, 0

            # ── 一致性判断 ──
            if train_ret > 0.02 and val_ret > 0.02:
                consistency = "CONSISTENT"
                verdict = "PASS"
            elif train_ret > 0.02 and val_ret <= 0:
                consistency = "OVERFIT"
                verdict = "FAIL"
            elif train_ret <= 0 and val_ret > 0.02:
                consistency = "LUCKY"
                verdict = "FAIL"
            else:
                consistency = "DEAD"
                verdict = "FAIL"

            tsr = TradingSimResult(
                factor_name=name,
                train_total_ret=train_ret,
                train_sharpe=train_sharpe,
                train_n_trades=train_nt,
                val_total_ret=val_ret,
                val_sharpe=val_sharpe,
                val_n_trades=val_nt,
                consistency=consistency,
                verdict=verdict,
            )
            report.trading_sim_results[name] = tsr
            report.final_verdicts[name] = verdict

            if self.verbose:
                status = "+" if verdict == "PASS" else "-"
                print(f"  [{status}] {name:<25s} "
                      f"Train_ret={train_ret:+.2%}({train_nt}t) "
                      f"Val_ret={val_ret:+.2%}({val_nt}t) "
                      f"→ {consistency}")

        # 选最优：Train+Val 都正收益，且 Val Sharpe 最高
        best_sharpe = -999
        for name, tsr in report.trading_sim_results.items():
            if tsr.verdict == "PASS" and tsr.val_sharpe > best_sharpe:
                best_sharpe = tsr.val_sharpe
                report.best_factor = name
                report.best_horizon = 5

        if self.verbose:
            if report.best_factor:
                tsr = report.trading_sim_results[report.best_factor]
                print(f"\n  ===> Best: {report.best_factor} "
                      f"Val_Sharpe={tsr.val_sharpe:.2f}  {tsr.consistency}")
            else:
                print(f"\n  ===> No factor passed consistency check")

        return report
