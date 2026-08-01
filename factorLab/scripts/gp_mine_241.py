"""
GP 挖掘 v2: 从 241 特征中自动发现最优因子公式
==============================================
6 段滚动 Train + 独立 Val, 严格时序隔离
"""
import sys, os, warnings
warnings.filterwarnings('ignore')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np
import pandas as pd
from scipy.stats import spearmanr as spr
from factor_lab.feature_builder import FeatureBuilder
from factor_lab.factor_miner import GPFactorMiner, FactorResult
from factor_lab.config import GPMinerConfig

# ── 加载 ──
csv_path = os.path.join(os.path.dirname(__file__), "..", "data", "300442_sz_daily.csv")
df = pd.read_csv(csv_path)
close = df["close"].values.astype(np.float64)
dates = df["trade_date"].astype(str).values
n = len(close)

fb = FeatureBuilder(windows=[5, 10, 20, 30, 60], verbose=True)
feat_dict = fb.build(df['open'].values, df['high'].values, df['low'].values,
                     df['close'].values, df['vol'].values)

# ── 目标: 未来 3 日收益 ──
target = np.full(n, np.nan)
target[:n-3] = close[3:] / close[:n-3] - 1.0
target = np.nan_to_num(target, nan=0.0)

# ── 预筛选 TOP 50 特征 ──
n_train = int(n * 0.60)
ic_scores = {}
for k, v in feat_dict.items():
    valid = np.isfinite(v[:n_train]) & (target[:n_train] != 0)
    if valid.sum() < 30:
        continue
    ic, _ = spr(v[:n_train][valid], target[:n_train][valid])
    ic_scores[k] = abs(ic) if np.isfinite(ic) else 0
top50 = sorted(ic_scores, key=ic_scores.get, reverse=True)[:50]
print(f"  TOP50 IC: {max(ic_scores.values()):.4f} ~ {min(ic_scores[k] for k in top50):.4f}")

# ── 构建 7 段: 6 Train + 1 Val ──
N_SEG = 6
seg_size = n_train // N_SEG
feat_list, label_list = [], []
for i in range(N_SEG):
    s, e = i * seg_size, min((i+1)*seg_size, n_train)
    chunk = {k: np.nan_to_num(np.float64(feat_dict[k][s:e]), nan=0.0) for k in top50}
    feat_list.append(chunk)
    label_list.append(target[s:e])
# Val
val_end = n_train + int(n * 0.20)
chunk = {k: np.nan_to_num(np.float64(feat_dict[k][n_train:val_end]), nan=0.0) for k in top50}
feat_list.append(chunk)
label_list.append(target[n_train:val_end])

print(f"  GP: {len(feat_list)} segments, {sum(len(l) for l in label_list)} samples, {len(top50)} features")

# ── 运行 GP ──
config = GPMinerConfig(
    population_size=100, n_generations=40, tournament_size=4,
    init_min_depth=1, init_max_depth=4, max_tree_height=6,
    crossover_prob=0.7, mutation_prob=0.3,
)
gp = GPFactorMiner(config)
result = gp.mine(feat_list, label_list, top50, use_pooled=False, seed=42, verbose=True)

if result:
    print(f"\n{'='*60}")
    print(f"  GP BEST FACTOR")
    print(f"{'='*60}")
    print(f"  Name:     {result.name}")
    print(f"  Formula:  {result.expression}")
    print(f"  Category: {result.category}")
    print(f"  Train IC: {result.train_ic:+.4f}")
    print(f"  Test IC:  {result.test_ic:+.4f}")
    print(f"  IC std:   {result.ic_std:.4f}")
    print(f"  ICIR:     {result.icir:.4f}")
    print(f"  Score:    {result.score:.4f}")
else:
    print("\n  GP failed, falling back to TemplateMiner...")
    from factor_lab.factor_miner import TemplateMiner
    tm = TemplateMiner()
    features_np = {k: np.nan_to_num(np.float64(feat_dict[k][:n_train]), nan=0.0) for k in top50}
    t_results = tm.mine(features_np, target[:n_train], top50, verbose=False)
    for i, r in enumerate(t_results[:8]):
        print(f"  [{i+1}] {r.name}: IC={r.train_ic:+.4f}, formula={r.expression}")
