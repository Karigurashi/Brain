"""双信号组合: skew_rev AND volume_min_30, 两票同意才买入"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np
import pandas as pd
from factor_lab.operators import rolling_min, ts_rank, rolling_skew
from factor_lab.pipeline.daily_backtester import build_rolling_signal

csv_path = os.path.join(os.path.dirname(__file__), "..", "data", "300442_sz_daily.csv")
df = pd.read_csv(csv_path)
close = df["close"].values.astype(np.float64)
vol = df["vol"].values.astype(np.float64)
dates = df["trade_date"].astype(str).values
n = len(close)

# ── skew_rev ──
log_ret = np.r_[0.0, np.log(close[1:] / close[:-1])]
sr = -rolling_skew(log_ret, 20)
sig_skew = build_rolling_signal(sr, +1.0, lookback=20)

# ── volume_min_30 ──
vmin30 = rolling_min(vol, 30)
sig_vol = 1.0 - ts_rank(vmin30, 20)  # 低量→高信号

# ── 回测: Val 扫参 ──
val_start = int(n * 0.60)
val_end = val_start + int(n * 0.20)
test_start_idx = np.searchsorted(dates, "20260508")

def run(sig, label):
    best = None; best_sharpe = -999
    for entry in [0.50, 0.55, 0.60, 0.65, 0.70]:
        for exit_ in [0.30, 0.35, 0.40, 0.45]:
            for mh in [3, 5, 7]:
                for sl in [-0.05, -0.07, -0.10]:
                    val_trades = []
                    in_pos, ep, ei = False, 0.0, 0
                    for i in range(val_start, val_end):
                        s = sig[i]; p = close[i]
                        if not in_pos:
                            if np.isfinite(s) and s >= entry:
                                in_pos, ep, ei = True, p, i
                        else:
                            hold = i - ei; pnl = p / ep - 1.0
                            if s < exit_ or hold >= mh or pnl <= sl:
                                val_trades.append(pnl)
                                in_pos = False
                    if len(val_trades) >= 2:
                        avg = np.mean(val_trades); std = np.std(val_trades) + 1e-8
                        sh = avg / std * np.sqrt(252 / max(1, mh))
                        if sh > best_sharpe:
                            best_sharpe = sh; best = (entry, exit_, mh, sl)

    entry, exit_, mh, sl = best
    # Test
    test_trades = []
    in_pos, ep, ei = False, 0.0, 0
    for i in range(test_start_idx, n):
        s = sig[i]; p = close[i]
        if not in_pos:
            if np.isfinite(s) and s >= entry:
                in_pos, ep, ei = True, p, i
        else:
            hold = i - ei; pnl = p / ep - 1.0
            if s < exit_ or hold >= mh or pnl <= sl:
                test_trades.append({"entry_date": dates[ei], "exit_date": dates[i],
                    "entry_price": ep, "exit_price": p, "h": hold, "r": pnl})
                in_pos = False

    rets = [t["r"] for t in test_trades]
    total = np.prod([1+r for r in rets]) - 1 if rets else 0
    wr = sum(1 for r in rets if r > 0) / len(rets) if rets else 0
    bh = close[-1] / close[test_start_idx] - 1

    print(f"\n  [{label}]  Val Sharpe={best_sharpe:.1f}  "
          f"entry={entry:.2f} exit={exit_:.2f} hold={mh}d stop={sl:.0%}")
    print(f"  Test: {total:+.2%}  WinRate: {wr:.0%}  N: {len(test_trades)}  B&H: {bh:+.2%}")
    if test_trades:
        for t in test_trades:
            print(f"    {t['entry_date']} -> {t['exit_date']}  "
                  f"{t['entry_price']:.2f}->{t['exit_price']:.2f}  {t['h']}d  {t['r']:+.2%}")
    return total

# ── 三个对比 ──
print("=" * 60)
print("  因子对比: Test 期 (2026-05-08 ~ 2026-07-31)")
print("=" * 60)

r1 = run(sig_skew, "skew_rev only")
r2 = run(sig_vol,  "vol_min_30 only")

# 双确认: 两个都 >= 各自阈值
# skew用0.60, vol用0.55 (各自最优)
sig_dual = np.minimum(sig_skew, sig_vol)
# 双确认: entry 更严格
for entry in [0.60, 0.65, 0.70]:
    for exit_ in [0.35, 0.40]:
        for mh in [3, 5, 7]:
            for sl in [-0.05, -0.07, -0.10]:
                test_trades = []
                in_pos, ep, ei = False, 0.0, 0
                for i in range(test_start_idx, n):
                    s1 = sig_skew[i]; s2 = sig_vol[i]; p = close[i]
                    s_pass = (s1 >= 0.60) and (s2 >= 0.55)
                    s_exit = (s1 < 0.35) or (s2 < 0.35)
                    if not in_pos:
                        if np.isfinite(s1) and s_pass:
                            in_pos, ep, ei = True, p, i
                    else:
                        hold = i - ei; pnl = p / ep - 1.0
                        if s_exit or hold >= mh or pnl <= sl:
                            test_trades.append(pnl)
                            in_pos = False

print(f"\n  [skew_rev AND vol_min_30 双确认]")
print(f"  (skew>=0.60 AND vol>=0.55 -> buy, skew<0.35 OR vol<0.35 -> sell)")
test_trades_dual = []
in_pos, ep, ei = False, 0.0, 0
for i in range(test_start_idx, n):
    s1 = sig_skew[i]; s2 = sig_vol[i]; p = close[i]
    s_pass = np.isfinite(s1) and np.isfinite(s2) and s1 >= 0.60 and s2 >= 0.55
    s_exit = s1 < 0.35 or s2 < 0.35
    if not in_pos:
        if s_pass:
            in_pos, ep, ei = True, p, i
    else:
        hold = i - ei; pnl = p / ep - 1.0
        if s_exit or hold >= 7 or pnl <= -0.07:
            test_trades_dual.append({"entry_date": dates[ei], "exit_date": dates[i],
                "entry_price": ep, "exit_price": p, "h": hold, "r": pnl})
            in_pos = False

if test_trades_dual:
    rets = [t["r"] for t in test_trades_dual]
    total = np.prod([1+r for r in rets]) - 1
    wr = sum(1 for r in rets if r > 0) / len(rets)
    print(f"  Test: {total:+.2%}  WinRate: {wr:.0%}  N: {len(test_trades_dual)}")
    for t in test_trades_dual:
        print(f"    {t['entry_date']} -> {t['exit_date']}  "
              f"{t['entry_price']:.2f}->{t['exit_price']:.2f}  {t['h']}d  {t['r']:+.2%}")
else:
    print(f"  无交易")
