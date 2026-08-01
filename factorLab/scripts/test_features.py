import pandas as pd, numpy as np, sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from factor_lab.feature_builder import FeatureBuilder

df = pd.read_csv(os.path.join(os.path.dirname(__file__), '..', 'data', '300442_sz_daily.csv'))
fb = FeatureBuilder(windows=[5, 10, 20, 30, 60])
features = fb.build(
    df['open'].values, df['high'].values, df['low'].values,
    df['close'].values, df['vol'].values,
)

print(f"数据: {len(df)}天  |  特征数: {len(features)}")
print(f"\n最后一天 (7/31) 特征值:")
for k in sorted(features.keys()):
    v = features[k][-1]
    if np.isfinite(v):
        print(f"  {k:35s} = {v:>12.4f}")
