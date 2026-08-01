"""
skew_rev 详细拆解: 7/31 10:30 vs 11:00
========================================
展开 20 天对数收益率, 看偏度怎么变的
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np
import pandas as pd

csv_path = os.path.join(os.path.dirname(__file__), "..", "data", "300442_sz_daily.csv")
df = pd.read_csv(csv_path)
close = df["close"].values
dates = df["trade_date"].astype(str).values

# 7/10 ~ 7/30 历史收盘 (19 天)
hist_20_close = close[-20:-1]
hist_20_dates = dates[-20:-1]

# 两个时点
p1, p2 = 61.08, 63.50  # 10:30 vs 11:00

def compute_window(hist_close_19, today_price):
    """hist_close_19: 前19天收盘 [day0..day18], today_price: 当天价 day19"""
    all_close = np.append(hist_close_19, today_price)
    log_ret = np.log(all_close[1:] / all_close[:-1])
    skew_val = float(pd.Series(log_ret).skew())
    return log_ret, skew_val

lr1, skew1 = compute_window(hist_20_close, p1)
lr2, skew2 = compute_window(hist_20_close, p2)

print("=" * 72)
print("  skew_rev = -skew(log_ret_20d)")
print("  skew > 0 = 左偏(恐慌)  skew < 0 = 右偏(亢奋)")
print("  skew_rev 越大 → 越恐慌 → 越该买")
print("=" * 72)

for label, p, lr, sk in [("10:30 @61.08", p1, lr1, skew1),
                           ("11:00 @63.50", p2, lr2, skew2)]:
    print(f"\n{'─'*72}")
    print(f"  {label}  对数收益偏度={sk:+.4f}  skew_rev={-sk:+.4f}")
    print(f"{'─'*72}")
    print(f"  {'日期':>10}  {'收盘':>8}  {'→':>3}  {'收盘':>8}  {'对数收益':>10}")
    print(f"  {'─'*55}")

    for i in range(19):
        d0 = hist_20_dates[i] if i < 19 else "TODAY"
        d1 = hist_20_dates[i+1] if i+1 < 19 else "TODAY"
        c0 = hist_20_close[i] if i < 19 else p
        c1 = hist_20_close[i+1] if i+1 < 19 else p
        if i == 18:
            # 最后一行: hist → today
            print(f"  {hist_20_dates[18]:>10}  {hist_20_close[18]:>8.2f}  {'→':>3}  {'TODAY':>8}  {lr[18]:>+10.4f}  *** 当天 ***")
        else:
            print(f"  {hist_20_dates[i]:>10}  {hist_20_close[i]:>8.2f}  {'→':>3}  {hist_20_close[i+1]:>8.2f}  {lr[i]:>+10.4f}")

    skew_val = float(pd.Series(lr).skew())
    print(f"\n  偏度 = {skew_val:+.4f}")
    print(f"  如果偏度<0 (右偏): 分布尾巴在右边, 大涨拉偏 → 不恐慌")
    print(f"  如果偏度>0 (左偏): 分布尾巴在左边, 大跌拉偏 → 恐慌")

# 对比
print(f"\n{'='*72}")
print(f"  对比")
print(f"  {'='*72}")
print(f"  10:30 当天收益: 57.90→61.08 = {np.log(61.08/57.90):+.4f}")
print(f"  11:00 当天收益: 57.90→63.50 = {np.log(63.50/57.90):+.4f}")
print(f"")
print(f"  前 18 天收益里, 最差的几个:")
lrs = np.log(hist_20_close[1:] / hist_20_close[:-1])
idx = np.argsort(lrs)
for j in range(5):
    i = idx[j]
    print(f"    {hist_20_dates[i]:>10}→{hist_20_dates[i+1]:>10}  {hist_20_close[i]:>8.2f}→{hist_20_close[i+1]:>8.2f}  {lrs[i]:>+10.4f}")
print(f"")
print(f"  10:30: 19 个收益里, 当天 +5.3% 排第几?  {(lrs < np.log(61.08/57.90)).sum()}/19")
print(f"  11:00: 19 个收益里, 当天 +9.2% 排第几?  {(lrs < np.log(63.50/57.90)).sum()}/19")
print(f"")
print(f"  当天的收益越大, 越把分布往右拉 → 左偏消失 → 卖出")
