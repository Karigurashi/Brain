"""TemplateMiner: 从 241 特征中评估预定义模板因子"""
import sys, os, warnings
warnings.filterwarnings('ignore')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np
import pandas as pd
from factor_lab.feature_builder import FeatureBuilder
from factor_lab.factor_miner import TemplateMiner
from factor_lab.operators import spearman_correlation

df = pd.read_csv(os.path.join(os.path.dirname(__file__), "..", "data", "300442_sz_daily.csv"))
close = df["close"].values.astype(np.float64)
n = len(close)

fb = FeatureBuilder(windows=[5, 10, 20, 30, 60], verbose=False)
feat = fb.build(df['open'].values, df['high'].values, df['low'].values,
                df['close'].values, df['vol'].values)

tgt = np.full(n, np.nan)
tgt[:n-3] = close[3:] / close[:n-3] - 1.0
tgt = np.nan_to_num(tgt, nan=0.0)

n_train = int(n * 0.60)
n_val = int(n * 0.20)
test_start = n_train + n_val

feat_train = {k: np.nan_to_num(np.float64(v[:n_train]), nan=0.0) for k, v in feat.items()}

tm = TemplateMiner()
results = tm.mine(feat_train, tgt[:n_train], list(feat.keys()), verbose=False)

print(f"{'Name':30s}  {'TrainIC':>8}  {'ValIC':>8}  {'TestIC':>8}  Formula")
print("=" * 100)
for r in results:
    fv = r.factor_values
    if fv is not None and len(fv) >= test_start:
        val_ic = spearman_correlation(fv[n_train:test_start], tgt[n_train:test_start])
        test_ic = spearman_correlation(fv[test_start:], tgt[test_start:])
    else:
        val_ic, test_ic = np.nan, np.nan
    print(f"{r.name:30s}  {r.train_ic:>+8.4f}  {val_ic:>+8.4f}  {test_ic:>+8.4f}  {r.expression}")
