"""
skew_rev + MA20 趋势过滤
========================
价格 < MA20 → 跳过买入（即使信号达标）
价格 >= MA20 → 正常交易
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np
import pandas as pd

csv_path = os.path.join(os.path.dirname(__file__), "..", "data", "300442_sz_daily.csv")
df = pd.read_csv(csv_path)
close = df["close"].values
dates = df["trade_date"].astype(str).values

# ── 计算 skew_rev ──
from factor_lab.operators import rolling_skew
from factor_lab.pipeline.daily_backtester import build_rolling_signal

log_ret = np.r_[0.0, np.log(close[1:] / close[:-1])]
skew_20d = rolling_skew(log_ret, 20)
skew_rev = -skew_20d
signal = build_rolling_signal(skew_rev, +1.0, lookback=20)

# ── MA20 ──
ma20 = pd.Series(close).rolling(20).mean().values

# ── 回测参数 ──
entry_threshold = 0.60
exit_threshold = 0.35
max_hold = 5
stop_loss = -0.07

# ── 回测 ──
def backtest(filter_trend=False, filter_label=""):
    trades = []
    in_pos, entry_price, entry_idx = False, 0.0, 0
    pos_hist = np.zeros(len(close))
    
    for i in range(len(close)):
        sig = signal[i]
        p = close[i]
        
        if not in_pos:
            if np.isfinite(sig) and sig >= entry_threshold:
                if filter_trend and not np.isnan(ma20[i]) and p < ma20[i]:
                    continue  # 趋势过滤: 价格在 MA20 以下不买
                in_pos = True
                entry_price = p
                entry_idx = i
                pos_hist[i] = 1
        else:
            pos_hist[i] = 1
            hold = i - entry_idx
            pnl = p / entry_price - 1.0
            exit_sig = sig < exit_threshold
            exit_timeout = hold >= max_hold
            exit_stop = pnl <= stop_loss
            if exit_sig or exit_timeout or exit_stop:
                reason = "sig" if exit_sig else ("timeout" if exit_timeout else "stop")
                trades.append({
                    "entry_date": dates[entry_idx], "exit_date": dates[i],
                    "entry_price": entry_price, "exit_price": p,
                    "hold_days": hold, "return": pnl, "reason": reason,
                })
                in_pos = False
    
    # 统计
    if not trades:
        return {"total_return": 0, "win_rate": 0, "n_trades": 0, "trades": []}
    rets = [t["return"] for t in trades]
    total_ret = np.prod([1 + r for r in rets]) - 1
    win_rate = sum(1 for r in rets if r > 0) / len(rets)
    
    # Test 期 B&H
    test_start = np.searchsorted(dates, "20260508")
    bh_return = close[-1] / close[test_start] - 1
    
    return {
        "total_return": total_ret, "win_rate": win_rate, "n_trades": len(trades),
        "trades": trades, "bh_return": bh_return,
    }

# ── 跑两种 ──
r1 = backtest(filter_trend=False, filter_label="原始")
r2 = backtest(filter_trend=True, filter_label="+MA20过滤")

print("=" * 70)
print("  skew_rev 回测对比: 原始 vs +MA20趋势过滤")
print("=" * 70)
for label, r in [("原始", r1), ("+MA20过滤", r2)]:
    print(f"\n  [{label}]")
    print(f"    总收益: {r['total_return']:+.2%}  |  胜率: {r['win_rate']:.1%}  |  交易: {r['n_trades']}笔")
    if r["trades"]:
        for t in r["trades"]:
            print(f"    {t['entry_date']} → {t['exit_date']}  "
                  f"{t['entry_price']:.2f}→{t['exit_price']:.2f}  "
                  f"{t['hold_days']}d  {t['return']:+.2%}  ({t['reason']})")
    total_ret = r['total_return']
    bh = r['bh_return']
    print(f"    B&H: {bh:+.2%}  |  超额: {total_ret-bh:+.2%}")

# 过滤掉了哪些
print(f"\n  {'='*70}")
print(f"  MA20 过滤效果:")
orig_entries = [t["entry_date"] for t in r1["trades"]]
filt_entries = [t["entry_date"] for t in r2["trades"]]
filtered_out = set(orig_entries) - set(filt_entries)
if filtered_out:
    for d in sorted(filtered_out):
        i = np.where(dates == d)[0][0]
        print(f"    过滤掉: {d}  price={close[i]:.2f}  MA20={ma20[i]:.2f}  price/MA20={close[i]/ma20[i]:.2%}")
else:
    print(f"    无交易被过滤")
