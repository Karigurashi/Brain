"""
单票全特征 IC 分析 v2
=======================
241 特征 vs 未来 1/3/5/10 日收益, Spearman IC
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np
import pandas as pd
from factor_lab.feature_builder import FeatureBuilder

csv_path = os.path.join(os.path.dirname(__file__), "..", "data", "300442_sz_daily.csv")
df = pd.read_csv(csv_path)
close = df["close"].values.astype(np.float64)
dates = df["trade_date"].astype(str).values
n = len(close)

# ── 构建全部特征 ──
fb = FeatureBuilder(windows=[5, 10, 20, 30, 60], verbose=False)
features = fb.build(df['open'].values, df['high'].values, df['low'].values,
                     df['close'].values, df['vol'].values)

def safe_ic(farr, fwd_ret):
    """Spearman IC, 返回 NaN 如果不可靠"""
    mask = np.isfinite(farr) & np.isfinite(fwd_ret)
    if mask.sum() < 30:
        return np.nan
    try:
        return farr[mask].corr(pd.Series(fwd_ret[mask]), method='spearman')
    except:
        return np.nan

# ── 未来收益 (pandas Series 方便 corr) ──
h_list = [1, 3, 5, 10]
rets = {}
for h in h_list:
    valid_n = n - h
    r = np.full(n, np.nan)
    r[:valid_n] = close[h:] / close[:valid_n] - 1.0
    rets[h] = pd.Series(r)

# 验证收益数据
for h in h_list:
    vc = rets[h].notna().sum()
    print(f"ret_{h}d: {vc} valid, range=[{rets[h].min():+.4f}, {rets[h].max():+.4f}]")

# ── IC 分析 ──
print(f"\n计算 {len(features)} 个特征的 IC ...")
results = []
for fname, farr in features.items():
    s = pd.Series(farr)
    ic1 = safe_ic(s, rets[1])
    ic3 = safe_ic(s, rets[3])
    ic5 = safe_ic(s, rets[5])
    ic10 = safe_ic(s, rets[10])
    ics = [x for x in [ic1, ic3, ic5, ic10] if not np.isnan(x)]
    results.append({
        "feature": fname,
        "IC_1d": ic1, "IC_3d": ic3, "IC_5d": ic5, "IC_10d": ic10,
        "IC_mean": np.mean(ics) if ics else np.nan,
        "|IC|_max": max([abs(x) for x in ics]) if ics else 0,
    })

rdf = pd.DataFrame(results).sort_values("|IC|_max", ascending=False)

# ── TOP 30 ──
print("\n" + "=" * 85)
print("  TOP 40 特征 (按 |IC| 最大绝对值)")
print("=" * 85)
print(f"  {'特征':38s}  {'IC_1d':>8}  {'IC_3d':>8}  {'IC_5d':>8}  {'IC_10d':>8}")
print(f"  {'─'*80}")
for _, row in rdf.head(40).iterrows():
    print(f"  {row['feature']:38s}  {row['IC_1d']:>+8.4f}  {row['IC_3d']:>+8.4f}  "
          f"{row['IC_5d']:>+8.4f}  {row['IC_10d']:>+8.4f}")

# ── 去重 ──
print(f"\n{'='*85}")
print(f"  TOP 互补特征 (两两 corr<0.4)")
print(f"{'='*85}")

selected = []
for _, row in rdf.head(100).iterrows():
    fname = row["feature"]
    farr = pd.Series(features[fname])
    dup = False
    for sel in selected:
        mask = farr.notna() & pd.Series(features[sel]).notna()
        if mask.sum() < 30:
            continue
        c = farr[mask].corr(pd.Series(features[sel])[mask])
        if abs(c) > 0.4:
            dup = True
            break
    if not dup:
        selected.append(fname)
        print(f"  [{len(selected)}] {fname:35s}  |IC|_max={row['|IC|_max']:.4f}  "
              f"IC_1d={row['IC_1d']:+.4f}  IC_3d={row['IC_3d']:+.4f}  IC_5d={row['IC_5d']:+.4f}")
        if len(selected) >= 10:
            break

print(f"\n  → {len(selected)} 个互补特征")
