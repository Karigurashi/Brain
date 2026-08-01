"""
日级高频回测引擎
===============
每根日线判断信号 → 进出场 → 多轮换手 → 复利累积。

用法:
    from factor_lab.pipeline.daily_backtester import DailyBacktester
    bt = DailyBacktester()
    result = bt.run(factor_values, close, dates, test_mask)
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Optional
from dataclasses import dataclass, field


@dataclass
class DailyBacktestResult:
    label: str = ""
    total_return: float = 0.0
    annual_return: float = 0.0
    sharpe_ratio: float = 0.0
    max_drawdown: float = 0.0
    n_trades: int = 0
    n_long: int = 0
    win_rate: float = 0.0
    buy_and_hold_return: float = 0.0
    avg_hold_days: float = 0.0
    trades_df: Optional[pd.DataFrame] = None
    cumulative_returns: Optional[np.ndarray] = None
    daily_returns: Optional[np.ndarray] = None

    def summary(self) -> str:
        return (f"total={self.total_return:+.2%}  ann={self.annual_return:+.2%}  "
                f"sharpe={self.sharpe_ratio:.2f}  maxdd={self.max_drawdown:+.2%}  "
                f"wr={self.win_rate:.1%}  trades={self.n_trades}  "
                f"avg_hold={self.avg_hold_days:.1f}d  B&H={self.buy_and_hold_return:+.2%}")


class DailyBacktester:
    """日级信号 → 即时进出场"""

    def __init__(
        self,
        entry_threshold: float = 0.6,   # 信号分位 > 此值 → 买入
        exit_threshold: float = 0.4,    # 信号分位 < 此值 → 卖出
        max_hold_days: int = 10,        # 最长持有天数（风控）
        stop_loss: float = -0.05,       # 止损线（-5%）
        commission: float = 0.0003,     # 单边手续费
        annual_days: int = 252,
        verbose: bool = True,
    ):
        self.entry_threshold = entry_threshold
        self.exit_threshold = exit_threshold
        self.max_hold_days = max_hold_days
        self.stop_loss = stop_loss
        self.commission = commission
        self.annual_days = annual_days
        self.verbose = verbose

    def run(
        self,
        factor_signal: np.ndarray,   # 日级信号 [n]，值越大越看多
        close: np.ndarray,
        dates: List[str],
        test_mask: np.ndarray,
    ) -> DailyBacktestResult:
        """
        日级回测。

        factor_signal: 日级信号值（已按 IC 方向校正），0~1 分位数
        """
        n = len(close)
        indices = np.where(test_mask)[0]
        if len(indices) < 5:
            return DailyBacktestResult(label="No data")

        trades = []
        in_position = False
        entry_idx = 0
        entry_price = 0.0
        daily_rets = np.zeros(len(indices))

        for t, idx in enumerate(indices):
            sig = factor_signal[idx]
            price = close[idx]

            if not np.isfinite(sig) or not np.isfinite(price):
                continue

            if not in_position:
                # 等买入信号
                if sig >= self.entry_threshold:
                    in_position = True
                    entry_idx = idx
                    entry_price = price
            else:
                hold_days = idx - entry_idx
                pnl = price / entry_price - 1.0 - 2 * self.commission

                # 出场条件: 信号转弱 OR 超时 OR 止损
                exit_triggered = (
                    sig < self.exit_threshold or
                    hold_days >= self.max_hold_days or
                    pnl <= self.stop_loss
                )

                if exit_triggered or idx == indices[-1]:
                    in_position = False
                    trades.append({
                        "entry_date": dates[entry_idx],
                        "exit_date": dates[idx],
                        "entry_idx": entry_idx,
                        "exit_idx": idx,
                        "entry_price": entry_price,
                        "exit_price": price,
                        "hold_days": hold_days,
                        "return": pnl,
                    })
                    daily_rets[t] = pnl
                else:
                    daily_rets[t] = 0.0  # 持仓中，日收益计入最终出场

        if not trades:
            return DailyBacktestResult(
                label="No trades",
                buy_and_hold_return=close[indices[-1]] / close[indices[0]] - 1.0,
            )

        tdf = pd.DataFrame(trades)
        returns = tdf["return"].values
        n_trades = len(tdf)

        # 复利
        total_ret = float(np.prod(1 + returns) - 1)
        n_years = len(indices) / self.annual_days
        ann_ret = (1 + total_ret) ** (1 / max(n_years, 0.05)) - 1
        ann_vol = float(np.std(returns) * np.sqrt(self.annual_days / max(n_trades, 1)))
        sharpe = ann_ret / (ann_vol + 1e-8)

        cum = np.cumprod(1 + returns)
        peak = np.maximum.accumulate(cum)
        mdd = float(np.min(cum / peak - 1))

        wr = float((returns > 0).mean())
        avg_hold = float(tdf["hold_days"].mean())
        bh = close[indices[-1]] / close[indices[0]] - 1.0

        result = DailyBacktestResult(
            label=f"Daily({self.entry_threshold}/{self.exit_threshold})",
            total_return=total_ret,
            annual_return=ann_ret,
            sharpe_ratio=sharpe,
            max_drawdown=mdd,
            n_trades=n_trades,
            n_long=n_trades,  # 全是做多
            win_rate=wr,
            buy_and_hold_return=bh,
            avg_hold_days=avg_hold,
            trades_df=tdf,
            cumulative_returns=cum,
            daily_returns=daily_rets,
        )

        if self.verbose:
            print(f"\n  {'='*55}")
            print(f"  Daily Trading Result")
            print(f"  {'='*55}")
            print(f"  {result.summary()}")
            if n_trades > 0:
                print(f"  Top trades: {tdf['return'].nlargest(3).values}")
                print(f"  Worst trades: {tdf['return'].nsmallest(3).values}")

        return result


def build_daily_signal(
    factor_values: np.ndarray,
    test_ic: float,
    close: np.ndarray,
) -> np.ndarray:
    """滚动分位数信号"""
    return build_rolling_signal(factor_values, test_ic, lookback=20)


def build_rolling_signal(
    factor_values: np.ndarray,
    ic_direction: float,
    lookback: int = 20,
) -> np.ndarray:
    """
    滚动分位数信号 [0, 1]，自适应非平稳因子。
    
    虽然 Spearman IC 在全量上接近0（均匀分布），但极端值
    (>0.70或<0.30) 对均值回归因子有真实预测力。
    """
    n = len(factor_values)
    signal = np.full(n, np.nan)

    fm = np.isfinite(factor_values)
    if fm.sum() < 10:
        return signal

    for i in range(n):
        if not fm[i]:
            continue
        start = max(0, i - lookback)
        window = factor_values[start:i + 1]
        wm = np.isfinite(window)
        if wm.sum() < 5:
            signal[i] = 0.5
            continue
        rank = (window[wm] < factor_values[i]).sum() / wm.sum()
        # 负 IC → 低因子值=高分位=买入信号
        if ic_direction < 0:
            rank = 1.0 - rank
        signal[i] = float(rank)

    return signal


def build_global_signal(
    factor_values: np.ndarray,
    ic_direction: float,
    train_mask: np.ndarray = None,
) -> np.ndarray:
    """
    全局标准化信号 — 用Train集均值/标准差做一次标准化，后面不再滚动。
    完全保留因子IC结构，零信息丢失。

    原理:
      Train上算: mu = mean(factor[train]), sigma = std(factor[train])
      signal[t] = (factor[t] - mu) / sigma * sign(ic_direction)

    返回: signal[n], 正=看多, 负=看空
    """
    n = len(factor_values)
    fm = np.isfinite(factor_values)
    if fm.sum() < 10:
        return np.full(n, np.nan)

    # 有 train_mask 就用 Train 统计量，否则全局
    if train_mask is not None and train_mask.sum() >= 15:
        tv = train_mask & fm
        mu = float(np.nanmean(factor_values[tv]))
        sigma = float(np.nanstd(factor_values[tv]))
    else:
        mu = float(np.nanmean(factor_values[fm]))
        sigma = float(np.nanstd(factor_values[fm]))

    if sigma < 1e-10:
        sigma = 1.0

    direction = np.sign(ic_direction)
    if direction == 0:
        direction = -1.0  # default: mean-reversion

    signal = np.full(n, np.nan)
    for i in range(n):
        if not fm[i]:
            continue
        z = (factor_values[i] - mu) / sigma
        z = np.clip(z, -4.0, 4.0)
        signal[i] = float(z * direction)

    return signal


def build_zscore_signal(
    factor_values: np.ndarray,
    ic_direction: float,
    lookback: int = 40,
    min_periods: int = 20,
) -> np.ndarray:
    """
    用滚动 z-score 构建日级信号，保留线性IC结构。

    原理:
      z[t] = (factor[t] - rolling_mean[t]) / rolling_std[t]
      signal[t] = z[t] * sign(ic)  （IC为正则同向，IC为负则反向）

    均值回归因子(vwap_trend, IC<0):
      - 因子值远低于均值 → z很负 → 翻转后 signal 很大 → 买入
      - 因子回归均值 → z≈0 → signal≈0 → 卖出

    动量因子(IC>0):
      - 因子值远高于均值 → z很正 → signal 很大 → 买入

    返回: signal[n] ∈ (-∞, +∞), 正=看多, 负=看空, 0=中性
    """
    n = len(factor_values)
    signal = np.full(n, np.nan)

    fm = np.isfinite(factor_values)
    if fm.sum() < min_periods:
        return signal

    # 滚动均值和标准差
    import pandas as pd
    s = pd.Series(factor_values)
    roll_mean = s.rolling(window=lookback, min_periods=min_periods).mean().values
    roll_std = s.rolling(window=lookback, min_periods=min_periods).std().values

    # z-score（clip 防极端值）
    for i in range(n):
        if not fm[i] or not np.isfinite(roll_mean[i]) or not np.isfinite(roll_std[i]):
            continue
        if roll_std[i] < 1e-10:
            signal[i] = 0.0
            continue
        z = (factor_values[i] - roll_mean[i]) / roll_std[i]
        z = np.clip(z, -4.0, 4.0)  # 裁剪极端值
        # IC 方向校正: IC<0 时翻转（均值回归），IC>0 时保持（动量）
        signal[i] = float(z * np.sign(ic_direction))

    return signal


def verify_signal_ic(
    signal: np.ndarray,
    close: np.ndarray,
    train_mask: np.ndarray,
    horizons: list = None,
) -> dict:
    """验证信号在多周期上的 IC"""
    from factor_lab.operators import spearman_correlation
    if horizons is None:
        horizons = [1, 3, 5, 10]

    results = {}
    for h in horizons:
        fwd = np.full(len(close), np.nan)
        fwd[:-h] = close[h:] / close[:-h] - 1.0
        valid = train_mask & np.isfinite(signal) & np.isfinite(fwd)
        if valid.sum() < 15:
            results[h] = np.nan
            continue
        ic = spearman_correlation(signal[valid], fwd[valid])
        results[h] = float(ic) if np.isfinite(ic) else 0.0
    return results
