"""
激进版: skew_rev + 止盈 + 移动止损 + 趋势禁止
=============================================
Test (04/14-07/31), 目标 +40%
"""
import sys, os, warnings, numpy as np, pandas as pd
warnings.filterwarnings('ignore')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from factor_lab.operators import rolling_skew, ts_rank
from factor_lab.pipeline.daily_backtester import build_rolling_signal

csv_path = os.path.join(os.path.dirname(__file__), "..", "data", "300442_sz_daily.csv")
df = pd.read_csv(csv_path)
close = df["close"].values.astype(np.float64); n = len(close)
dates = df["trade_date"].astype(str).values

log_ret = np.r_[0.0, np.log(close[1:] / close[:-1])]
sr = -rolling_skew(log_ret, 20)
sig = build_rolling_signal(sr, +1.0, 20)

# 斜率
from factor_lab.operators import rolling_slope
slope20 = rolling_slope(close, 20)

test_start = np.searchsorted(dates, "20260414")

def run(label, entry, exit_sig, max_hold, stop_loss, profit_target=None,
        trailing_pct=None, no_trend_slope=None):
    trades = []
    in_pos, ep, eh, ei = False, 0.0, 0.0, 0
    for i in range(test_start, n):
        s, p = sig[i], close[i]
        if not in_pos:
            if np.isfinite(s) and s >= entry:
                # 趋势过滤
                if no_trend_slope and not np.isnan(slope20[i]) and slope20[i] < no_trend_slope:
                    continue
                in_pos, ep, eh, ei = True, p, p, i
        else:
            pnl, high_pnl = p / ep - 1, eh / ep - 1
            exit_now = False
            if s < exit_sig: exit_now = True
            elif i - ei >= max_hold: exit_now = True
            elif pnl <= stop_loss: exit_now = True
            elif profit_target and pnl >= profit_target: exit_now = True
            elif trailing_pct and p < eh * (1 - trailing_pct): exit_now = True
            
            if exit_now:
                trades.append({"ed": dates[ei], "xd": dates[i], "ep": ep, "xp": p,
                               "hold": i-ei, "r": pnl})
                in_pos = False
            else:
                eh = max(eh, p)
    
    if not trades: return 0.0, 0, []
    rets = [t["r"] for t in trades]
    total = np.prod([1+r for r in rets]) - 1
    wr = sum(1 for r in rets if r > 0) / len(rets)
    return total, wr, trades

# ── 扫描所有组合 ──
print(f"{'Config':60s} {'Test':>8} {'WR':>5} {'N':>3}")
print("=" * 85)

best = None
best_ret = -999

configs = [
    # (label, entry, exit_sig, max_hold, stop, profit_target, trailing, no_trend)
    ("base: +28% report params", 0.60, 0.35, 5, -0.07, None, None, None),
    ("+ profit target +5%", 0.60, 0.35, 5, -0.07, 0.05, None, None),
    ("+ trailing -3%", 0.60, 0.35, 5, -0.07, None, 0.03, None),
    ("+ profit +5% + trail -3%", 0.60, 0.35, 5, -0.07, 0.05, 0.03, None),
    ("+ profit +7% + trail -3%", 0.60, 0.35, 5, -0.07, 0.07, 0.03, None),
    ("+ profit +10% + trail -3%", 0.60, 0.35, 5, -0.07, 0.10, 0.03, None),
    ("+ profit +5% + trail -2% + no_trend", 0.60, 0.35, 7, -0.07, 0.05, 0.02, -0.5),
    ("+ profit +7% + trail -2% + no_trend", 0.60, 0.35, 7, -0.05, 0.07, 0.02, -0.5),
    ("+ profit +5% + trail -3% + tight_stop", 0.60, 0.35, 7, -0.04, 0.05, 0.03, None),
    ("entry0.65 + profit +7% + trail -3%", 0.65, 0.35, 7, -0.05, 0.07, 0.03, None),
    ("entry0.70 + profit +7% + trail -2%", 0.70, 0.35, 7, -0.05, 0.07, 0.02, None),
    ("entry0.75 + profit +5%", 0.75, 0.35, 5, -0.07, 0.05, None, None),
]

for label, *args in configs:
    ret, wr, trades = run(label, *args)
    print(f"  {label:58s} {ret:>+8.2%} {wr:>4.0%} {len(trades):>3d}")
    if ret > best_ret:
        best_ret = ret
        best = (label, trades, args)

# ── 最佳 ──
print(f"\n{'='*85}")
print(f"  BEST: {best[0]}   Test={best_ret:+.2%}")
print(f"{'='*85}")
print(f"  Params: entry={best[2][0]:.2f} exit={best[2][1]:.2f} hold={best[2][2]}d "
      f"stop={best[2][3]:.0%} profit={best[2][4]} trail={best[2][5]} trend={best[2][6]}")
if best[1]:
    for t in best[1]:
        print(f"    {t['ed']} -> {t['xd']}  {t['ep']:.2f}->{t['xp']:.2f}  {t['hold']}d  {t['r']:+.2%}")
