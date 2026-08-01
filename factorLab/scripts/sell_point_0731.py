"""
7/31 日内精确卖点反推 v3
=========================
全量历史算信号, 7/31 日内每个采样价替换当天收盘, 重算 skew_rev 和分位
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np
import pandas as pd
from factor_lab.operators import rolling_skew
from factor_lab.pipeline.daily_backtester import build_rolling_signal

csv_path = os.path.join(os.path.dirname(__file__), "..", "data", "300442_sz_daily.csv")
df = pd.read_csv(csv_path)
close_full = df["close"].values
dates_full = df["trade_date"].astype(str).values
n = len(close_full)

# 7/31 前 19 天收盘 (7/10~7/30)
prev19 = close_full[-20:-1]  # indices 227~246, 19 values

open_p, high_p, low_p, close_p = 61.94, 65.95, 61.08, 63.25

# 基准: 用收盘价 63.25 算信号
close_base = close_full.copy()
log_ret_base = np.r_[0.0, np.log(close_base[1:] / close_base[:-1])]
skew_base = rolling_skew(log_ret_base, 20)
sr_base = -skew_base
sig_base = build_rolling_signal(sr_base, +1.0, lookback=20)

print(f"基准(收盘63.25): skew_rev={sr_base[-1]:.4f}  signal={sig_base[-1]:.4f}")

# 对于每个采样价, 替换最后一天, 重算 skew_rev[-1], 看它在 sig_base[-21:-1] 中的分位
# 因为有 20 天 lookback, 我们需要最近 20 个历史信号的分位
# 简化: 看当前 skew_rev 在过去 20 个 skew_rev 中的分位
hist_sr = sr_base[-21:-1]  # 前 20 个 skew_rev 值

times = ["09:30","10:00","10:30","11:00","11:30","13:00","13:30","14:00","14:30","15:00"]
prices_path = [61.94, 61.50, 61.08, 63.50, 65.20, 65.95, 65.00, 64.20, 63.60, 63.25]

print("\n" + "=" * 65)
print("  7/31 日内采样 — 信号分位 (vs 前20天skew_rev分布)")
print(f"  前收(7/30)=57.90  开={open_p} 低={low_p} 高={high_p}")
print("=" * 65)
print(f"  {'时间':>8}  {'价格':>8}  {'skew_rev':>10}  {'分位':>7}  {'操作':>12}")
print("-" * 65)

for t, p in zip(times, prices_path):
    # 用采样价替换最后一天
    c2 = close_full[:-1].copy()
    c2 = np.append(c2, p)
    lr2 = np.r_[0.0, np.log(c2[1:] / c2[:-1])]
    sk2 = rolling_skew(lr2, 20)
    sr2 = -sk2
    new_sr = sr2[-1]
    
    # 分位 = 前20天中有多少 <= new_sr
    pct = np.mean(hist_sr <= new_sr)
    
    if pct >= 0.60:
        op = ">>> BUY <<<"
    elif pct < 0.35:
        op = "<<< SELL <<<"
    else:
        op = "HOLD"
    print(f"  {t:>8}  {p:>8.2f}  {new_sr:>10.4f}  {pct:>7.4f}  {op:>16}")

print("-" * 65)

# 找临界价
print("\n  精细扫描 (找分位≈0.35 临界):")
prev_pct = None
for p in np.arange(low_p, high_p + 0.05, 0.05):
    c2 = close_full[:-1].copy()
    c2 = np.append(c2, p)
    lr2 = np.r_[0.0, np.log(c2[1:] / c2[:-1])]
    sk2 = rolling_skew(lr2, 20)
    sr2 = -sk2
    pct = np.mean(hist_sr <= sr2[-1])
    mark = ""
    if prev_pct is not None and (prev_pct - 0.35) * (pct - 0.35) <= 0:
        mark = " ←←← 卖出临界!"
    if pct < 0.5:
        print(f"  {p:>8.2f}  {sr2[-1]:>10.4f}  {pct:>7.4f}{mark}")
    prev_pct = pct
