"""
skew_rev 因子近期信号速查
=========================
直接用报告参数 (entry=0.60, exit=0.35, max_hold=5, stop_loss=-0.07)
输出最近 30 个交易日的信号和模拟交易
"""
import sys, os
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import numpy as np
from factor_lab.operators import rolling_skew
from factor_lab.pipeline.daily_backtester import DailyBacktester, build_rolling_signal

# ── 加载数据 ──
csv_path = os.path.join(os.path.dirname(__file__), "..", "data", "300442_sz_daily.csv")
df = pd.read_csv(csv_path)
close = df["close"].values
dates = df["trade_date"].astype(str).values
n = len(close)

# ── 计算 skew_rev 因子 ──
# skew_rev = -skew_20d, where skew_20d = rolling_skew(log_ret, 20)
log_ret = np.r_[0.0, np.log(close[1:] / close[:-1])]
skew_20d = rolling_skew(log_ret, 20)
skew_rev = -skew_20d

# ── 报告参数 ──
# IC = +0.30 (正 → 因子值高 = 未来涨 → signal = rank, 不翻转)
ic_direction = +1.0
signal = build_rolling_signal(skew_rev, ic_direction, lookback=20)

# ── 构建 DataFrame ──
df["skew_rev"] = skew_rev
df["signal"] = signal

# ── 只看最近 30 个交易日 ──
recent = df.tail(30).copy()
print("\n" + "=" * 80)
print("  skew_rev 因子 — 最近 30 个交易日信号")
print("  (IC=+0.30, entry≥0.60 买入, exit<0.35 卖出, max_hold=5天, stop_loss=-7%)")
print("=" * 80)
print(f"{'日期':>10}  {'收盘':>8}  {'skew_rev':>10}  {'信号':>7}  {'状态':>12}")
print("-" * 80)

in_pos = False
entry_price = 0.0
entry_date = ""
entry_idx_global = 0
trades = []

for _, row in recent.iterrows():
    idx = row.name
    price = row["close"]
    sig = row["signal"]
    date = str(row["trade_date"])
    sk = row["skew_rev"]

    status = ""
    if not in_pos:
        if np.isfinite(sig) and sig >= 0.60:
            in_pos = True
            entry_price = price
            entry_date = date
            entry_idx_global = idx
            status = f">> BUY @{price:.2f}"
        else:
            status = "--"
    else:
        hold_days = idx - entry_idx_global
        pnl = price / entry_price - 1.0
        exit_signal = sig < 0.35
        exit_timeout = hold_days >= 5
        exit_stop = pnl <= -0.07

        if exit_signal or exit_timeout or exit_stop:
            reason = ""
            if exit_signal: reason = "信号减弱"
            elif exit_timeout: reason = "超时"
            elif exit_stop: reason = "止损"
            status = f"<< SELL @{price:.2f} ({reason})"
            trades.append({
                "entry_date": entry_date, "exit_date": date,
                "entry_price": entry_price, "exit_price": price,
                "hold_days": hold_days, "return": pnl,
            })
            in_pos = False
        else:
            status = f"HOLD day{hold_days}"

    print(f"  {date}  {price:>8.2f}  {sk:>10.4f}  {sig:>7.4f}  {status:>12}")

print("-" * 80)

# ── 交易汇总 ──
if trades:
    print(f"\n  近期交易明细:")
    print(f"  {'买入日':>10}  {'卖出日':>10}  {'买入价':>8}  {'卖出价':>8}  {'持仓':>5}  {'收益':>8}")
    print(f"  {'-'*65}")
    for t in trades:
        print(f"  {t['entry_date']:>10}  {t['exit_date']:>10}  {t['entry_price']:>8.2f}  {t['exit_price']:>8.2f}  {t['hold_days']:>4}天  {t['return']:>+8.2%}")
    total_ret = np.prod([1 + t["return"] for t in trades]) - 1
    print(f"\n  累计: {total_ret:+.2%}  |  交易次数: {len(trades)}")
else:
    print("\n  无交易触发")

# ── 全量回测对比 ──
print("\n" + "=" * 80)
print("  全量 Test 期回测 (skew_rev)")
print("=" * 80)
test_start_idx = np.searchsorted(dates, "20260508")
test_mask = np.zeros(n, dtype=bool)
test_mask[test_start_idx:] = True

bt = DailyBacktester(entry_threshold=0.60, exit_threshold=0.35,
                     max_hold_days=5, stop_loss=-0.07, verbose=True)
result = bt.run(signal, close, dates, test_mask)

if result.trades_df is not None:
    print(f"\n  全部交易明细:")
    tdf = result.trades_df
    for _, t in tdf.iterrows():
        print(f"  {t['entry_date']:>10} → {t['exit_date']:>10}  "
              f"买入{t['entry_price']:>8.2f}  卖出{t['exit_price']:>8.2f}  "
              f"{t['hold_days']:>3}天  {t['return']:>+8.2%}")
