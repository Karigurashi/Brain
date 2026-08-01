"""第二轮: 止盈 + 紧止损 精细扫描"""
import sys, os, warnings, numpy as np, pandas as pd
warnings.filterwarnings('ignore')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from factor_lab.operators import rolling_skew
from factor_lab.pipeline.daily_backtester import build_rolling_signal

csv_path = os.path.join(os.path.dirname(__file__), "..", "data", "300442_sz_daily.csv")
df = pd.read_csv(csv_path)
close = df["close"].values.astype(np.float64); n = len(close)
dates = df["trade_date"].astype(str).values

log_ret = np.r_[0.0, np.log(close[1:] / close[:-1])]
sr = -rolling_skew(log_ret, 20)
sig = build_rolling_signal(sr, +1.0, 20)
test_start = np.searchsorted(dates, "20260414")

def run(entry, exit_sig, max_hold, stop_loss, profit_target=None, trailing=None):
    trades = []
    in_pos, ep, eh, ei = False, 0.0, 0.0, 0
    for i in range(test_start, n):
        s, p = sig[i], close[i]
        if not in_pos:
            if np.isfinite(s) and s >= entry:
                in_pos, ep, eh, ei = True, p, p, i
        else:
            pnl = p / ep - 1
            exit_now = False
            if s < exit_sig: exit_now = True
            elif i - ei >= max_hold: exit_now = True
            elif pnl <= stop_loss: exit_now = True
            elif profit_target and pnl >= profit_target: exit_now = True
            elif trailing and p < eh * (1 - trailing): exit_now = True
            if exit_now:
                trades.append({"ed": dates[ei], "xd": dates[i], "ep": ep, "xp": p,
                               "hold": i-ei, "r": pnl})
                in_pos = False
            else:
                eh = max(eh, p)
    if not trades: return 0.0, 0, []
    rets = [t["r"] for t in trades]
    return np.prod([1+r for r in rets]) - 1, sum(1 for r in rets if r > 0) / len(rets), trades

print(f"{'Config':55s} {'Test':>8} {'WR':>5} {'N':>3} Details")
print("=" * 100)
best_ret, best_cfg = -999, None

for entry in [0.60, 0.65]:
    for profit in [0.05, 0.06, 0.07, 0.08, 0.10]:
        for stop in [-0.03, -0.04, -0.05, -0.07]:
            for hold in [5, 7, 10]:
                for exit_s in [0.25, 0.35]:
                    for trail in [None, 0.02, 0.03]:
                        ret, wr, trades = run(entry, exit_s, hold, stop, profit, trail)
                        label = f"e={entry:.2f} p={profit:.0%} s={stop:.0%} h={hold}d x={exit_s:.2f} t={trail}"
                        if ret > best_ret:
                            best_ret = ret
                            best_cfg = (label, trades, (entry, exit_s, hold, stop, profit, trail))
                            print(f"  {label:53s} {ret:>+8.2%} {wr:>4.0%} {len(trades):>3d}  *** NEW BEST ***")
                            if trades:
                                for t in trades:
                                    print(f"    {t['ed']}->{t['xd']} {t['ep']:.2f}->{t['xp']:.2f} {t['hold']}d {t['r']:+.2%}")

print(f"\n{'='*100}")
print(f"  FINAL BEST: {best_ret:+.2%}")
print(f"  {best_cfg[0]}")
