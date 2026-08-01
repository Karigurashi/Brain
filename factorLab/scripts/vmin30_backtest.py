"""volume_min_30 因子回测 — IC=-0.40 地量反转"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np
import pandas as pd
from factor_lab.operators import rolling_min, ts_rank

csv_path = os.path.join(os.path.dirname(__file__), "..", "data", "300442_sz_daily.csv")
df = pd.read_csv(csv_path)
close = df["close"].values.astype(np.float64)
vol = df["vol"].values.astype(np.float64)
dates = df["trade_date"].astype(str).values
n = len(close)

# ── volume_min_30: 30日最低成交量 ──
vmin30 = rolling_min(vol, 30)

# IC 为负: vmin30 越低 → 未来涨 → flip 信号
# 信号 = 1 - ts_rank(vmin30, 20): 地量→高分位
rank = ts_rank(vmin30, 20)
signal = 1.0 - rank  # 低成交量 → 高信号

# ── 回测 ──
def backtest(sig, entry_thresh, exit_thresh, max_hold, stop_loss, label=""):
    trades = []
    in_pos, entry_price, entry_idx = False, 0.0, 0
    test_start = np.searchsorted(dates, "20260508")

    for i in range(len(close)):
        s = sig[i]
        p = close[i]
        if not in_pos:
            if np.isfinite(s) and s >= entry_thresh:
                in_pos = True
                entry_price = p
                entry_idx = i
        else:
            hold = i - entry_idx
            pnl = p / entry_price - 1.0
            if s < exit_thresh or hold >= max_hold or pnl <= stop_loss:
                trades.append({"entry_date": dates[entry_idx], "exit_date": dates[i],
                    "entry_price": entry_price, "exit_price": p,
                    "hold_days": hold, "return": pnl})
                in_pos = False

    if not trades:
        return {"total_return": 0, "win_rate": 0, "n_trades": 0, "trades": []}

    rets = [t["return"] for t in trades]
    total_ret = np.prod([1 + r for r in rets]) - 1
    win_rate = sum(1 for r in rets if r > 0) / len(rets)

    # B&H from test start
    bh = close[-1] / close[test_start] - 1

    # Only trades in test period
    test_trades = [t for t in trades if t["entry_date"] >= "20260508"]
    test_rets = [t["return"] for t in test_trades]
    test_ret = np.prod([1 + r for r in test_rets]) - 1 if test_rets else 0
    test_wr = sum(1 for r in test_rets if r > 0) / len(test_rets) if test_rets else 0

    return {"total_return": total_ret, "win_rate": win_rate, "n_trades": len(trades),
            "trades": trades, "bh_return": bh, "test_return": test_ret,
            "test_wr": test_wr, "test_n": len(test_trades), "test_trades": test_trades}

# ── 扫参 (Val 期) ──
val_start = int(n * 0.60)
val_end = val_start + int(n * 0.20)

best_sharpe = -999
best_params = None

for entry in [0.55, 0.60, 0.65, 0.70, 0.75]:
    for exit_ in [0.30, 0.35, 0.40, 0.45]:
        for mh in [3, 5, 7]:
            for sl in [-0.05, -0.07, -0.10]:
                # Only evaluate on val period
                val_trades = []
                in_pos, ep, ei = False, 0.0, 0
                for i in range(val_start, val_end):
                    s = signal[i]; p = close[i]
                    if not in_pos:
                        if np.isfinite(s) and s >= entry:
                            in_pos, ep, ei = True, p, i
                    else:
                        hold = i - ei; pnl = p / ep - 1.0
                        if s < exit_ or hold >= mh or pnl <= sl:
                            val_trades.append(pnl)
                            in_pos = False
                if len(val_trades) >= 2:
                    avg = np.mean(val_trades)
                    std = np.std(val_trades) + 1e-8
                    sharpe = avg / std * np.sqrt(252 / max(1, mh))
                    if sharpe > best_sharpe:
                        best_sharpe = sharpe
                        best_params = (entry, exit_, mh, sl)

print(f"Val 最优: entry={best_params[0]:.2f} exit={best_params[1]:.2f} "
      f"hold={best_params[2]}d stop={best_params[3]:.0%}  Sharpe={best_sharpe:.2f}")

# ── Test 期回测(仅最优参数) ──
entry, exit_, mh, sl = best_params
test_trades = []
in_pos, ep, ei = False, 0.0, 0
test_start = np.searchsorted(dates, "20260508")
for i in range(test_start, n):
    s = signal[i]; p = close[i]
    if not in_pos:
        if np.isfinite(s) and s >= entry:
            in_pos, ep, ei = True, p, i
    else:
        hold = i - ei; pnl = p / ep - 1.0
        if s < exit_ or hold >= mh or pnl <= sl:
            test_trades.append({"entry_date": dates[ei], "exit_date": dates[i],
                "entry_price": ep, "exit_price": p, "hold_days": hold, "return": pnl})
            in_pos = False

print(f"\n{'='*70}")
print(f"  volume_min_30 因子 Test 期回测")
print(f"  entry>=0.60  exit<0.35  max_hold={mh}d  stop_loss={sl:.0%}")
print(f"{'='*70}")

if test_trades:
    print(f"  {'买入':>10}  {'卖出':>10}  {'买入价':>8}  {'卖出价':>8}  {'持仓':>5}  {'收益':>8}")
    print(f"  {'─'*55}")
    for t in test_trades:
        print(f"  {t['entry_date']:>10}  {t['exit_date']:>10}  "
              f"{t['entry_price']:>8.2f}  {t['exit_price']:>8.2f}  "
              f"{t['hold_days']:>3}d  {t['return']:>+8.2%}")
    rets = [t["return"] for t in test_trades]
    total = np.prod([1+r for r in rets]) - 1
    wr = sum(1 for r in rets if r > 0) / len(rets)
    bh = close[-1] / close[test_start] - 1
    print(f"\n  Test: {total:+.2%}  WinRate: {wr:.0%}  B&H: {bh:+.2%}  Trades: {len(test_trades)}")
else:
    print("  无交易")

# ── 最近信号 ──
print(f"\n  最近 10 日信号:")
for i in range(max(0, n-10), n):
    print(f"    {dates[i]:>10}  close={close[i]:>7.2f}  vmin30={vmin30[i]:>10.0f}  signal={signal[i]:.4f}")
