"""
Pipeline Stage 6: RegimeBacktester
==================================
Regime 自适应的样本外回测引擎。

核心逻辑:
  每天:
    1. 判断当前 Regime（用已训练的 Regime 检测器）
    2. 选择该 Regime 对应的最优因子
    3. 因子信号 → 仓位决策 → 执行交易
    4. 记录交易明细 + 累积收益

支持:
  - 单一因子 / 多因子等权 / Top-N 投票 三种信号融合模式
  - 做多阈值控制
  - Buy & Hold 基准对比

依赖: factor_lab.evaluation.BacktestEngine
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field


@dataclass
class RegimeBacktestResult:
    """Regime 切换回测结果"""
    label: str = ""
    total_return: float = 0.0
    annual_return: float = 0.0
    sharpe_ratio: float = 0.0
    max_drawdown: float = 0.0
    n_trades: int = 0
    n_long: int = 0
    win_rate: float = 0.0
    buy_and_hold_return: float = 0.0
    # Regime 维度统计
    regime_performance: Dict[int, Dict] = field(default_factory=dict)
    # 详细
    trades_df: Optional[pd.DataFrame] = None
    cumulative_returns: Optional[np.ndarray] = None
    # 对比
    baseline_result: Optional[Dict] = None  # 不使用 Regime 切换的基准回测

    def summary(self) -> str:
        return (f"总收益={self.total_return:+.2%}  年化={self.annual_return:+.2%}  "
                f"Sharpe={self.sharpe_ratio:.2f}  MaxDD={self.max_drawdown:+.2%}  "
                f"胜率={self.win_rate:.1%}  B&H={self.buy_and_hold_return:+.2%}")


class RegimeBacktester:
    """
    Regime 自适应回测引擎。

    根据每天检测到的 Regime，调用对应的最优因子生成信号。
    纯样本外：仅使用测试期数据，不回头偷看。

    Example:
        backtester = RegimeBacktester(
            prediction_days=10, signal_mode="best_per_regime",
            long_threshold=0.0,
        )
        result = backtester.run(
            validated_factors, features, target,
            close, dates, regime_result, test_mask,
        )
    """

    def __init__(
        self,
        prediction_days: int = 10,
        signal_mode: str = "best_per_regime",
        long_threshold: float = 0.0,
        commission_rate: float = 0.0003,
        annual_days: int = 252,
        verbose: bool = True,
    ):
        """
        Args:
            prediction_days: 预测天数（持仓周期）
            signal_mode: 信号融合模式
                - "best_per_regime": 每 Regime 选最优因子
                - "ensemble": 多因子等权平均
                - "top3_vote": Top-3 投票（2/3 同意才做多）
            long_threshold: 做多信号阈值
            commission_rate: 单边手续费
            annual_days: 年化天数
            verbose: 详细输出
        """
        self.prediction_days = prediction_days
        self.signal_mode = signal_mode
        self.long_threshold = long_threshold
        self.commission_rate = commission_rate
        self.annual_days = annual_days
        self.verbose = verbose

    def run(
        self,
        validated_factors: Dict[int, List],
        features: Dict[str, np.ndarray],
        target: np.ndarray,
        close: np.ndarray,
        dates: List[str],
        regime_labels: np.ndarray,
        test_mask: np.ndarray,
        compare_baseline: bool = True,
    ) -> RegimeBacktestResult:
        """
        执行 Regime 自适应回测。

        Args:
            validated_factors: {regime_id: [FactorResult, ...]} — 已验证因子
            features: 特征字典
            target: 目标收益（仅用于统计，不用于决策）
            close: 收盘价序列
            dates: 日期序列
            regime_labels: 全量 Regime 标签 [n]
            test_mask: 测试集掩码

        Returns:
            RegimeBacktestResult
        """
        n = len(close)
        pred_days = self.prediction_days
        start_delay = int(test_mask.argmax()) if test_mask.any() else 30

        # ── 预处理: 提取每个因子在测试期的值 ──
        factor_signals = self._prepare_signals(validated_factors, test_mask)

        if not factor_signals:
            if self.verbose:
                print("  [回测] 无可用的验证因子，回测中止")
            return RegimeBacktestResult(label="No signals")

        # ── 逐日回测 ──
        trades = []
        i = start_delay
        while i + pred_days < n:
            if not test_mask[i]:
                i += 1
                continue

            curr_regime = int(regime_labels[i])

            # 获取信号
            signal = self._get_signal(factor_signals, curr_regime, i)
            position = 1 if (signal is not None and signal > self.long_threshold) else 0

            entry_price = close[i]
            exit_price = close[i + pred_days]
            gross_ret = exit_price / entry_price - 1.0
            net_ret = (gross_ret - 2 * self.commission_rate) if position == 1 else 0.0

            trades.append({
                "index": i,
                "date": dates[i] if i < len(dates) else str(i),
                "regime": curr_regime,
                "entry_price": entry_price,
                "exit_price": exit_price,
                "signal": float(signal) if signal is not None else 0.0,
                "position": position,
                "return": net_ret,
            })
            i += pred_days

        if not trades:
            return RegimeBacktestResult(label="No trades")

        tdf = pd.DataFrame(trades)

        # ── 汇总统计 ──
        returns = tdf["return"].values
        n_trades = len(tdf)
        n_long = int(tdf["position"].sum())
        total_ret = float(np.prod(1 + returns) - 1)

        n_years = max(n_trades * pred_days / self.annual_days, 0.05)
        ann_ret = (1 + total_ret) ** (1 / n_years) - 1
        ann_vol = float(np.std(returns) * np.sqrt(self.annual_days / pred_days))
        sharpe = ann_ret / (ann_vol + 1e-8)

        cum = np.cumprod(1 + returns)
        peak = np.maximum.accumulate(cum)
        mdd = float(np.min(cum / peak - 1))

        long_returns = returns[tdf["position"] == 1]
        wr = float((long_returns > 0).mean()) if len(long_returns) > 0 else 0.0

        bh_return = close[-1] / close[start_delay] - 1.0

        # ── Per-Regime 统计 ──
        regime_perf = {}
        for ri in tdf["regime"].unique():
            rt = tdf[tdf["regime"] == ri]
            rr = rt["return"].values
            regime_perf[int(ri)] = {
                "n_trades": len(rt),
                "n_long": int(rt["position"].sum()),
                "total_return": float(np.prod(1 + rr) - 1),
                "win_rate": float((rt["return"] > 0).mean()),
                "avg_return": float(np.mean(rr)),
            }

        result = RegimeBacktestResult(
            label=f"RegimeAdaptive({self.signal_mode})",
            total_return=total_ret,
            annual_return=ann_ret,
            sharpe_ratio=sharpe,
            max_drawdown=mdd,
            n_trades=n_trades,
            n_long=n_long,
            win_rate=wr,
            buy_and_hold_return=bh_return,
            regime_performance=regime_perf,
            trades_df=tdf,
            cumulative_returns=cum,
        )

        # ── 基准对比：不用 Regime 切换，所有因子等权 ──
        if compare_baseline and factor_signals:
            baseline = self._run_baseline(
                factor_signals, close, dates, test_mask, start_delay)
            result.baseline_result = baseline

        if self.verbose:
            self._print_result(result)

        return result

    def _prepare_signals(
        self,
        validated_factors: Dict[int, List],
        test_mask: np.ndarray,
    ) -> Dict[int, List[Dict]]:
        """提取每个因子的信号序列"""
        signals: Dict[int, List[Dict]] = {}
        for ri, factors in validated_factors.items():
            ri_signals = []
            for f in factors:
                if f.factor_values is not None:
                    ri_signals.append({
                        "name": f.name,
                        "values": f.factor_values,
                        "test_ic": f.test_ic,
                        "category": f.category,
                    })
            if ri_signals:
                signals[ri] = ri_signals
        return signals

    def _get_signal(
        self,
        factor_signals: Dict[int, List[Dict]],
        curr_regime: int,
        idx: int,
    ) -> Optional[float]:
        """根据当前 Regime 获取信号值"""
        # 如果当前 Regime 没有因子，回退到最近的有因子的 Regime
        regime_factors = factor_signals.get(curr_regime)
        if not regime_factors:
            # 回退到所有因子的等权平均
            all_factors = []
            for fs in factor_signals.values():
                all_factors.extend(fs)
            if not all_factors:
                return None
            regime_factors = all_factors

        if self.signal_mode == "best_per_regime":
            # 选 test_ic 绝对值最大的，转分位数信号，负IC自动翻转
            best = max(regime_factors, key=lambda f: abs(f["test_ic"]))
            val = best["values"][idx]
            if not np.isfinite(val):
                return None
            all_vals = best["values"]
            fm = np.isfinite(all_vals)
            if fm.sum() < 10:
                return float(val)
            rank = (all_vals[fm] < val).sum() / fm.sum()
            if best["test_ic"] < 0:
                rank = 1.0 - rank  # 负IC: 低因子值=高分位=做多
            return float(rank)

        elif self.signal_mode == "top3_vote":
            # Top-3 投票
            sorted_fs = sorted(regime_factors,
                               key=lambda f: abs(f["test_ic"]), reverse=True)[:3]
            votes = 0
            for f in sorted_fs:
                val = f["values"][idx]
                if np.isfinite(val) and val > self.long_threshold:
                    votes += 1
            return 1.0 if votes >= 2 else 0.0

        else:  # ensemble
            vals = []
            for f in regime_factors:
                val = f["values"][idx]
                if np.isfinite(val):
                    # 按 IC 方向翻转，IC 权重
                    direction = 1.0 if f["test_ic"] > 0 else -1.0
                    weight = abs(f["test_ic"]) + 0.01
                    vals.append(val * direction * weight)
            if not vals:
                return None
            total_weight = sum(abs(f["test_ic"]) + 0.01 for f in regime_factors
                              if np.isfinite(f["values"][idx]))
            return float(np.sum(vals) / (total_weight + 1e-8))

    def _run_baseline(
        self,
        factor_signals: Dict[int, List[Dict]],
        close: np.ndarray,
        dates: List[str],
        test_mask: np.ndarray,
        start_delay: int,
    ) -> Dict:
        """不使用 Regime 切换的基准回测（所有因子等权）"""
        all_factors = []
        for fs in factor_signals.values():
            all_factors.extend(fs)

        if not all_factors:
            return {}

        n = len(close)
        pred_days = self.prediction_days
        returns = []

        i = start_delay
        while i + pred_days < n:
            if not test_mask[i]:
                i += 1
                continue
            vals = []
            for f in all_factors:
                val = f["values"][i]
                if np.isfinite(val):
                    vals.append(val)
            signal = np.mean(vals) if vals else 0.0
            position = 1 if signal > self.long_threshold else 0
            ret = (close[i + pred_days] / close[i] - 1.0 - 2 * self.commission_rate) if position == 1 else 0.0
            returns.append(ret)
            i += pred_days

        if not returns:
            return {}

        returns = np.array(returns)
        total_ret = float(np.prod(1 + returns) - 1)
        n_years = max(len(returns) * pred_days / self.annual_days, 0.05)
        ann_ret = (1 + total_ret) ** (1 / n_years) - 1
        cum = np.cumprod(1 + returns)
        peak = np.maximum.accumulate(cum)
        mdd = float(np.min(cum / peak - 1))

        return {
            "total_return": total_ret,
            "annual_return": ann_ret,
            "max_drawdown": mdd,
            "n_trades": len(returns),
        }

    def _print_result(self, result: RegimeBacktestResult):
        """打印回测报告"""
        print(f"\n{'='*65}")
        print(f"  Regime 自适应回测结果")
        print(f"{'='*65}")
        print(f"  {result.summary()}")
        print(f"\n  Per-Regime 表现:")
        print(f"  {'Regime':<8} {'交易数':>6} {'做多':>5} {'收益':>8} {'胜率':>7}")
        print(f"  {'─'*40}")
        for ri, perf in sorted(result.regime_performance.items()):
            print(f"  R{ri:<7} {perf['n_trades']:>6} {perf['n_long']:>5} "
                  f"{perf['total_return']:>+7.2%} {perf['win_rate']:>7.1%}")

        if result.baseline_result:
            bl = result.baseline_result
            print(f"\n  基准对比 (无Regime切换,等权):")
            print(f"    总收益={bl['total_return']:+.2%}  "
                  f"年化={bl['annual_return']:+.2%}  "
                  f"MaxDD={bl['max_drawdown']:+.2%}")
            delta = result.total_return - bl["total_return"]
            print(f"    Regime切换超额: {delta:+.2%}")
