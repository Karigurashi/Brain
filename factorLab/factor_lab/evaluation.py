"""
因子评估 & 回测引擎模块
======================
提供完整的因子评估体系和简易回测引擎。

评估六维:
  1. IC 均值 — 因子与未来收益的相关性
  2. ICIR    — IC均值/IC标准差，稳定性指标
  3. IC胜率  — IC为正的期数占比
  4. t统计量 — IC显著不为零的t检验
  5. IC趋势  — IC是否随时间衰减
  6. 综合评级 — S/A/B/C/D 五级

回测引擎:
  - 支持 LONG-only / LONG-SHORT 两种模式
  - 软阈值(Soft) / 硬阈值(Hard) 两种信号生成
  - 输出: 总收益、Sharpe、MaxDD、WinRate、交易明细

用法:
    from factor_lab.evaluation import FactorEvaluator, BacktestEngine
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Tuple, Callable
from dataclasses import dataclass, field
from factor_lab.config import BacktestConfig


# ================================================================
# 评估结果数据结构
# ================================================================

@dataclass
class EvalMetrics:
    """因子评估指标"""
    mean_ic: float = 0.0
    ic_std: float = 0.0
    icir: float = 0.0          # Information Coefficient IR
    ic_win_rate: float = 0.0   # IC > 0 的占比
    t_stat: float = 0.0        # IC t 统计量
    ic_trend: str = "flat"     # "up" / "down" / "flat"
    n_periods: int = 0
    rating: str = "D"          # S/A/B/C/D
    rating_score: int = 0      # 0-11 分

    def summary(self) -> str:
        return (f"IC={self.mean_ic:+.4f}  IR={self.icir:.3f}  "
                f"Win={self.ic_win_rate:.1%}  t={self.t_stat:.2f}  "
                f"趋势={self.ic_trend}  评级={self.rating}({self.rating_score}/11)")


@dataclass
class BacktestResult:
    """回测结果"""
    label: str = ""
    total_return: float = 0.0          # 总收益率
    annual_return: float = 0.0         # 年化收益率
    annual_volatility: float = 0.0     # 年化波动率
    sharpe_ratio: float = 0.0          # 夏普比率
    max_drawdown: float = 0.0          # 最大回撤
    n_trades: int = 0                  # 交易笔数
    n_long: int = 0                    # 做多笔数
    win_rate: float = 0.0              # 胜率
    buy_and_hold_return: float = 0.0   # 买入持有收益
    trades_df: Optional[pd.DataFrame] = None   # 交易明细
    cumulative_returns: Optional[np.ndarray] = None

    def summary(self) -> str:
        return (f"总收益={self.total_return:+.2%}  Sharpe={self.sharpe_ratio:.2f}  "
                f"MaxDD={self.max_drawdown:+.2%}  WinRate={self.win_rate:.1%}  "
                f"笔数={self.n_trades}(LONG={self.n_long})")


# ================================================================
# 因子评估器
# ================================================================

class FactorEvaluator:
    """
    因子六维评估器。

    评估 IC 序列的质量，给出 S/A/B/C/D 五级综合评级。

    Example:
        evaluator = FactorEvaluator()
        metrics = evaluator.evaluate(ic_sequence, factor_name="my_factor")
    """

    def evaluate(
        self,
        ics: List[float],
        factor_name: str = "",
        verbose: bool = True,
    ) -> EvalMetrics:
        """
        评估一组 IC 序列。

        Args:
            ics: IC 值列表 (每期一个 IC)
            factor_name: 因子名称（用于打印）
            verbose: 是否打印报告

        Returns:
            EvalMetrics
        """
        if not ics or len(ics) < 5:
            return EvalMetrics(n_periods=len(ics))

        ics_arr = np.array(ics)
        n = len(ics_arr)

        # 基础统计
        mean_ic = float(np.mean(ics_arr))
        ic_std = float(np.std(ics_arr, ddof=1))
        icir = mean_ic / ic_std if ic_std > 1e-12 else 0.0
        ic_win_rate = float((ics_arr > 0).mean())
        t_stat = float(mean_ic / (ic_std / np.sqrt(n))) if ic_std > 1e-12 else 0.0

        # IC 趋势 (线性回归斜率)
        if n >= 6:
            x = np.arange(n)
            slope = np.polyfit(x, ics_arr, 1)[0]
            if slope > 0.001:
                ic_trend = "up"
            elif slope < -0.001:
                ic_trend = "down"
            else:
                ic_trend = "flat"
        else:
            ic_trend = "flat"

        # 综合评分 (0-11 分)
        rating_score, rating = self._compute_rating(
            mean_ic, icir, ic_win_rate, t_stat, ic_trend)

        metrics = EvalMetrics(
            mean_ic=mean_ic,
            ic_std=ic_std,
            icir=icir,
            ic_win_rate=ic_win_rate,
            t_stat=t_stat,
            ic_trend=ic_trend,
            n_periods=n,
            rating=rating,
            rating_score=rating_score,
        )

        if verbose:
            self._print_report(factor_name, metrics, ics_arr)

        return metrics

    @staticmethod
    def _compute_rating(
        mean_ic: float,
        icir: float,
        win_rate: float,
        t_stat: float,
        ic_trend: str,
    ) -> Tuple[int, str]:
        """综合评分 → 五级评级"""
        score = 0

        # IC 绝对值 (0-3分)
        abs_ic = abs(mean_ic)
        if abs_ic >= 0.05:
            score += 3
        elif abs_ic >= 0.03:
            score += 2
        elif abs_ic >= 0.01:
            score += 1

        # ICIR (0-3分)
        abs_ir = abs(icir)
        if abs_ir >= 1.0:
            score += 3
        elif abs_ir >= 0.5:
            score += 2
        elif abs_ir >= 0.2:
            score += 1

        # 胜率 (0-3分)
        if win_rate >= 0.65:
            score += 3
        elif win_rate >= 0.55:
            score += 2
        elif win_rate >= 0.50:
            score += 1

        # t统计量 (0-2分)
        abs_t = abs(t_stat)
        if abs_t >= 3.0:
            score += 2
        elif abs_t >= 2.0:
            score += 1

        # 降级: IC趋势向下扣分
        if ic_trend == "down":
            score = max(0, score - 1)

        # 分级
        if score >= 10:
            rating = "S"
        elif score >= 8:
            rating = "A"
        elif score >= 6:
            rating = "B"
        elif score >= 4:
            rating = "C"
        else:
            rating = "D"

        return score, rating

    @staticmethod
    def _print_report(name: str, m: EvalMetrics, ics: np.ndarray):
        """打印评估报告"""
        header = f"  [{name}]" if name else ""
        print(f"\n{'─'*55}")
        print(f"  因子评估报告 {header}")
        print(f"{'─'*55}")
        print(f"  截面数: {m.n_periods}")
        print(f"  IC均值: {m.mean_ic:+.4f}    IC标准差: {m.ic_std:.4f}")
        print(f"  ICIR:   {m.icir:.3f}       IC胜率:   {m.ic_win_rate:.1%}")
        print(f"  t统计量: {m.t_stat:.2f}     IC趋势:   {m.ic_trend}")
        print(f"  综合评级: {m.rating} ({m.rating_score}/11)")
        print(f"  IC序列: [{', '.join(f'{v:+.4f}' for v in ics[:6])}"
              f"{', ...' if len(ics) > 6 else ''}]")


# ================================================================
# 回测引擎
# ================================================================

class BacktestEngine:
    """
    简易向量化回测引擎。

    支持:
      - LONG-only（仅做多）
      - 固定预测周期的等权重策略
      - 软阈值信号（连续值 > threshold 即做多）
      - 多阈值快速对比

    Example:
        engine = BacktestEngine(BacktestConfig(prediction_days=10))
        result = engine.run(signal, close, dates)
    """

    def __init__(self, config: Optional[BacktestConfig] = None):
        self.config = config or BacktestConfig()

    def run(
        self,
        signal: np.ndarray,
        close: np.ndarray,
        dates: Optional[List[str]] = None,
        label: str = "Strategy",
        threshold: float = 0.0,
    ) -> Optional[BacktestResult]:
        """
        运行回测。

        Args:
            signal: 因子信号序列 [n]，> threshold 则做多
            close: 收盘价序列 [n]
            dates: 日期序列 [n]（可选）
            label: 策略标签
            threshold: 做多阈值

        Returns:
            BacktestResult 或 None（数据不足）
        """
        n = len(close)
        pred_days = self.config.prediction_days
        start_delay = self.config.start_delay

        trades = []
        i = start_delay
        while i + pred_days < n:
            sig = signal[i]
            position = 1 if (np.isfinite(sig) and sig > threshold) else 0
            entry_price = close[i]
            exit_price = close[i + pred_days]
            ret = exit_price / entry_price - 1.0 if position == 1 else 0.0

            trades.append({
                "index": i,
                "date": dates[i] if dates else str(i),
                "entry_price": entry_price,
                "exit_price": exit_price,
                "signal": sig,
                "position": position,
                "return": ret * position,
            })
            i += pred_days

        if not trades:
            return None

        tdf = pd.DataFrame(trades)
        returns = tdf["return"].values

        # 统计指标
        n_trades = len(tdf)
        n_long = int(tdf["position"].sum())
        total_ret = float(np.prod(1 + returns) - 1)
        n_years = max(n_trades * pred_days / self.config.annual_days, 0.05)

        ann_ret = (1 + total_ret) ** (1 / n_years) - 1
        ann_vol = float(np.std(returns) * np.sqrt(self.config.annual_days / pred_days))
        sharpe = ann_ret / (ann_vol + 1e-8)

        # 回撤
        cum = np.cumprod(1 + returns)
        peak = np.maximum.accumulate(cum)
        mdd = float(np.min(cum / peak - 1))

        # 胜率
        long_returns = returns[tdf["position"] == 1]
        wr = float((long_returns > 0).mean()) if len(long_returns) > 0 else 0.0

        # 买入持有
        bh_return = close[-1] / close[start_delay] - 1.0

        return BacktestResult(
            label=label,
            total_return=total_ret,
            annual_return=ann_ret,
            annual_volatility=ann_vol,
            sharpe_ratio=sharpe,
            max_drawdown=mdd,
            n_trades=n_trades,
            n_long=n_long,
            win_rate=wr,
            buy_and_hold_return=bh_return,
            trades_df=tdf,
            cumulative_returns=cum,
        )

    def compare_thresholds(
        self,
        signal: np.ndarray,
        close: np.ndarray,
        dates: Optional[List[str]] = None,
        thresholds: List[float] = None,
        label: str = "Strategy",
    ) -> List[BacktestResult]:
        """
        多阈值对比回测。

        Args:
            thresholds: 阈值列表，默认 [0.0, 0.15, 0.3]

        Returns:
            各阈值下的回测结果列表
        """
        if thresholds is None:
            thresholds = [0.0, 0.15, 0.3]

        results = []
        for thr in thresholds:
            result = self.run(signal, close, dates,
                             label=f"{label} (thr={thr})",
                             threshold=thr)
            if result:
                results.append(result)
        return results

    def print_comparison(self, results: List[BacktestResult]):
        """打印多阈值对比表"""
        if not results:
            print("  无有效回测结果")
            return

        print(f"\n  {'策略':<28s} {'总收益':>8s} {'Sharpe':>7s} "
              f"{'MaxDD':>8s} {'胜率':>7s} {'笔数':>5s} {'LONG':>5s} {'B&H':>8s}")
        print(f"  {'─'*85}")
        for r in results:
            print(f"  {r.label:<28s} {r.total_return:>+8.2%} {r.sharpe_ratio:>7.2f} "
                  f"{r.max_drawdown:>+8.2%} {r.win_rate:>7.1%} "
                  f"{r.n_trades:>5d} {r.n_long:>5d} {r.buy_and_hold_return:>+8.2%}")

    def print_trades(self, result: BacktestResult, max_rows: int = 20):
        """打印交易明细"""
        if result.trades_df is None:
            return
        tdf = result.trades_df
        print(f"\n  交易明细 ({len(tdf)} 笔):")
        print(f"  {'日期':<12s} {'入场':>8s} {'出场':>8s} "
              f"{'方向':>6s} {'收益':>8s}")
        print(f"  {'─'*50}")
        for _, t in tdf.head(max_rows).iterrows():
            pos = "LONG" if t["position"] == 1 else "FLAT"
            print(f"  {str(t['date']):<12s} {t['entry_price']:>8.2f} "
                  f"{t['exit_price']:>8.2f} {pos:>6s} {t['return']:>+8.4f}")
        if len(tdf) > max_rows:
            print(f"  ... 共 {len(tdf)} 笔，仅显示前 {max_rows} 笔")


# ================================================================
# 便利函数: 从 FactorResult 列表快速评估 + 回测
# ================================================================

def evaluate_all_factors(
    factors: List,
    features: Dict[str, np.ndarray],
    target: np.ndarray,
    train_mask: np.ndarray,
    test_mask: np.ndarray,
    label: str = "",
) -> pd.DataFrame:
    """
    批量评估一组因子，返回汇总 DataFrame。

    每个 factor 需有 .factor_values 属性 (np.ndarray)。

    Returns:
        DataFrame with columns: name, category, train_ic, test_ic, score, rating
    """
    from factor_lab.operators import spearman_correlation

    evaluator = FactorEvaluator()
    rows = []

    for f in factors:
        if f.factor_values is None:
            continue
        fv = f.factor_values

        # 分段 IC
        train_valid = train_mask & np.isfinite(target) & np.isfinite(fv)
        test_valid = test_mask & np.isfinite(target) & np.isfinite(fv)

        train_ic = spearman_correlation(fv[train_valid], target[train_valid])
        test_ic = spearman_correlation(fv[test_valid], target[test_valid])

        rows.append({
            "name": f.name,
            "category": f.category,
            "train_ic": train_ic if np.isfinite(train_ic) else 0.0,
            "test_ic": test_ic if np.isfinite(test_ic) else 0.0,
            "score": f.score,
            "logic": f.logic_description,
        })

    df = pd.DataFrame(rows)
    if len(df) > 0:
        df = df.sort_values("score", ascending=False).reset_index(drop=True)

    return df
