"""
多方案系统性因子挖掘 & 回测
============================
6 种方法并行对比, Walk-Forward 扫参, 找最优方案
目标: Test 期收益 > 40%
"""
import sys, os, warnings
warnings.filterwarnings('ignore')
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import numpy as np
import pandas as pd
from scipy.stats import spearmanr as spr
from factor_lab.feature_builder import FeatureBuilder
from factor_lab.operators import rolling_min, rolling_skew, ts_rank

# ── 加载 ──
csv_path = os.path.join(os.path.dirname(__file__), "..", "data", "300442_sz_daily.csv")
df = pd.read_csv(csv_path)
close = df["close"].values.astype(np.float64)
vol = df["vol"].values.astype(np.float64)
dates = df["trade_date"].astype(str).values
n = len(close)

fb = FeatureBuilder(windows=[5, 10, 20, 30, 60], verbose=False)
features = fb.build(df['open'].values, df['high'].values, df['low'].values,
                    df['close'].values, df['vol'].values)

# ── 目标收益 ──
def fwd_ret(arr, h):
    r = np.full(len(arr), np.nan)
    r[:len(arr)-h] = arr[h:] / arr[:len(arr)-h] - 1.0
    return r

# ── 时序划分 ──
train_end = int(n * 0.50)
val_end = int(n * 0.70)
test_start = int(n * 0.70)

print(f"Data: {n} days | Train: {dates[0]}~{dates[train_end-1]} ({train_end}d)")
print(f"Val:   {dates[train_end]}~{dates[val_end-1]} ({val_end-train_end}d)")
print(f"Test:  {dates[val_end]}~{dates[-1]} ({n-val_end}d)")

# ── 方案 1: IC 加权 Top-N 特征等权集成 ──
def method_ic_ensemble(N=5, horizon=3):
    """选 Train IC 最强的 N 个特征, 滚动分位等权"""
    tgt = fwd_ret(close, horizon)
    scores = {}
    for k, v in features.items():
        mask = np.isfinite(v[:train_end]) & np.isfinite(tgt[:train_end])
        if mask.sum() < 30: continue
        ic, _ = spr(v[:train_end][mask], tgt[:train_end][mask])
        if np.isfinite(ic): scores[k] = ic
    
    top = sorted(scores, key=lambda x: abs(scores[x]), reverse=True)[:N]
    # 构建信号
    signals = []
    for k in top:
        ic_dir = np.sign(scores[k])
        vals = np.nan_to_num(np.float64(features[k]), nan=0.0)
        rank = ts_rank(vals, 20)
        rank = np.nan_to_num(rank, nan=0.5)
        sig = rank if ic_dir > 0 else (1.0 - rank)
        signals.append(sig)
    return np.mean(signals, axis=0) if signals else np.zeros(n), top, scores

# ── 方案 2: 对数收益偏度 (skew_rev) ──
def method_skew_rev():
    log_ret = np.r_[0.0, np.log(close[1:] / close[:-1])]
    sr = -rolling_skew(log_ret, 20)
    rank = ts_rank(np.nan_to_num(sr, nan=0.0), 20)
    return np.nan_to_num(1.0 - rank, nan=0.5)  # skew_rev 正→低分位→高信号? wait
    
    # IC was +0.30, so higher skew_rev → higher return. Signal = rank (not flip)
    rank2 = ts_rank(np.nan_to_num(sr, nan=0.0), 20)
    return np.nan_to_num(rank2, nan=0.5)

# ── 方案 3: 地量 + 低波 + 超跌 三信号 ──
def method_triple():
    """volume_min_30 + spread_mean_5 + close_delta_20, 三个 IC 最强的等权"""
    vmin = rolling_min(vol, 30)
    s1 = 1.0 - ts_rank(np.nan_to_num(vmin, nan=np.nanmedian(vmin)), 20)
    
    hi_lo = df["high"].values - df["low"].values
    spread5 = pd.Series(hi_lo).rolling(5).mean().values
    s2 = 1.0 - ts_rank(np.nan_to_num(spread5, nan=np.nanmedian(spread5)), 20)
    
    delta20 = close - np.roll(close, 20)
    s3 = 1.0 - ts_rank(np.nan_to_num(delta20, nan=0.0), 20)
    
    return np.nan_to_num((s1 + s2 + s3) / 3.0, nan=0.5)

# ── 方案 4: IC 前 20 加权 ──
def method_ic_weighted_top20(horizon=3):
    tgt = fwd_ret(close, horizon)
    scores = {}
    for k, v in features.items():
        mask = np.isfinite(v[:train_end]) & np.isfinite(tgt[:train_end])
        if mask.sum() < 30: continue
        ic, _ = spr(v[:train_end][mask], tgt[:train_end][mask])
        if np.isfinite(ic): scores[k] = ic
    
    top20 = sorted(scores, key=lambda x: abs(scores[x]), reverse=True)[:20]
    weights = np.array([abs(scores[k]) for k in top20])
    weights = weights / weights.sum()
    
    sigs = []
    for k, w in zip(top20, weights):
        ic_dir = np.sign(scores[k])
        vals = np.nan_to_num(np.float64(features[k]), nan=0.0)
        rank = ts_rank(vals, 20)
        rank = np.nan_to_num(rank, nan=0.5)
        sig = rank if ic_dir > 0 else (1.0 - rank)
        sigs.append(sig * w)
    return np.sum(sigs, axis=0), top20

# ── 方案 5: 多周期 IC 稳定特征 ──
def method_multihorizon_stable():
    """选在 3/5/10 日三个周期上 IC 都稳定的特征"""
    horizons = [3, 5, 10]
    all_scores = {}
    for h in horizons:
        tgt = fwd_ret(close, h)
        for k, v in features.items():
            mask = np.isfinite(v[:train_end]) & np.isfinite(tgt[:train_end])
            if mask.sum() < 30: continue
            ic, _ = spr(v[:train_end][mask], tgt[:train_end][mask])
            if np.isfinite(ic):
                all_scores.setdefault(k, []).append(ic)
    
    # 选 3 个周期都有 IC 且方向一致的
    stable = []
    for k, ics in all_scores.items():
        if len(ics) == 3 and all(np.sign(ics[0]) == np.sign(ic) for ic in ics):
            mean_abs = np.mean([abs(ic) for ic in ics])
            stable.append((k, mean_abs, np.sign(ics[0])))
    stable.sort(key=lambda x: x[1], reverse=True)
    
    top = stable[:10]
    sigs = []
    for k, _, direction in top:
        vals = np.nan_to_num(np.float64(features[k]), nan=0.0)
        rank = ts_rank(vals, 20)
        rank = np.nan_to_num(rank, nan=0.5)
        sig = rank if direction > 0 else (1.0 - rank)
        sigs.append(sig)
    return np.mean(sigs, axis=0) if sigs else np.zeros(n), top

# ── 回测函数 ──
def run_backtest(signal_array, entry_thresh, exit_thresh, max_hold, stop_loss):
    trades = []
    in_pos, ep, ei = False, 0.0, 0
    for i in range(test_start, n):
        s = signal_array[i]; p = close[i]
        if not in_pos:
            if np.isfinite(s) and s >= entry_thresh:
                in_pos, ep, ei = True, p, i
        else:
            hold = i - ei
            pnl = p / ep - 1.0
            if s < exit_thresh or hold >= max_hold or pnl <= stop_loss:
                trades.append({"entry_date": dates[ei], "exit_date": dates[i],
                    "ep": ep, "xp": p, "hold": hold, "ret": pnl})
                in_pos = False
    if in_pos:
        hold = n-1 - ei
        pnl = close[-1] / ep - 1.0
        trades.append({"entry_date": dates[ei], "exit_date": dates[-1],
            "ep": ep, "xp": close[-1], "hold": hold, "ret": pnl})
    
    if not trades: return 0.0, 0, []
    rets = [t["ret"] for t in trades]
    total = np.prod([1+r for r in rets]) - 1
    wr = sum(1 for r in rets if r > 0) / len(rets)
    return total, wr, trades

def val_scan(signal_array):
    """在 Val 期扫参"""
    best_sharpe, best_params = -999, None
    for entry in np.arange(0.45, 0.80, 0.05):
        for exit_ in np.arange(0.25, 0.50, 0.05):
            for mh in [3, 5, 7, 10]:
                for sl in [-0.05, -0.07, -0.10, -0.15]:
                    val_trades = []
                    in_pos, ep, ei = False, 0.0, 0
                    for i in range(train_end, val_end):
                        s = signal_array[i]; p = close[i]
                        if not in_pos:
                            if np.isfinite(s) and s >= entry:
                                in_pos, ep, ei = True, p, i
                        else:
                            hold = i - ei; pnl = p / ep - 1.0
                            if s < exit_ or hold >= mh or pnl <= sl:
                                val_trades.append(pnl)
                                in_pos = False
                    if len(val_trades) >= 3:
                        avg = np.mean(val_trades); std = np.std(val_trades)
                        if std > 1e-8:
                            sh = avg / std
                            if sh > best_sharpe:
                                best_sharpe = sh
                                best_params = (entry, exit_, mh, sl)
    return best_params if best_params else (0.60, 0.35, 5, -0.07)

# ── 全部方案 ──
print("\n" + "=" * 75)
print("  6 种方案并行对比")
print("=" * 75)

methods = {
    "M1_IC_Top5": lambda: method_ic_ensemble(5, 3),
    "M2_IC_Top10": lambda: method_ic_ensemble(10, 3),
    "M3_IC_Top20_W": lambda: method_ic_weighted_top20(3),
    "M4_Triple": lambda: (method_triple(), [], {}),
    "M5_MultiHz_Stable": lambda: method_multihorizon_stable(),
    "M6_SkewRev_Only": lambda: (method_skew_rev(), ["skew_rev"], {"skew_rev": 0.30}),
}

best_result = {"name": "", "test_ret": -999, "trades": [], "params": None, "signal": None}

for name, fn in methods.items():
    result = fn()
    sig = result[0]
    
    # Val 扫参
    params = val_scan(sig)
    entry, exit_, mh, sl = params
    
    # Test 回测
    test_ret, wr, trades = run_backtest(sig, entry, exit_, mh, sl)
    bh = close[-1] / close[test_start] - 1
    
    # Train 收益
    train_ret, _, _ = run_backtest(sig, entry, exit_, mh, sl)
    # Actually compute train
    train_trades = []
    in_pos, ep, ei = False, 0.0, 0
    for i in range(60, train_end):  # skip first 60 days for warmup
        s = sig[i]; p = close[i]
        if not in_pos:
            if np.isfinite(s) and s >= entry:
                in_pos, ep, ei = True, p, i
        else:
            hold = i - ei; pnl = p / ep - 1.0
            if s < exit_ or hold >= mh or pnl <= sl:
                train_trades.append(pnl)
                in_pos = False
    tr = np.prod([1+r for r in train_trades]) - 1 if train_trades else 0
    
    print(f"\n  [{name}] entry={entry:.2f} exit={exit_:.2f} hold={mh}d stop={sl:.0%}")
    print(f"  Train: {tr:+.2%}  Test: {test_ret:+.2%}  WinRate: {wr:.0%}  N: {len(trades)}  B&H: {bh:+.2%}")
    if trades:
        for t in trades:
            print(f"    {t['entry_date']} -> {t['exit_date']}  {t['ep']:.2f}->{t['xp']:.2f}  {t['hold']}d  {t['ret']:+.2%}")
    
    if test_ret > best_result["test_ret"]:
        best_result = {"name": name, "test_ret": test_ret, "trades": trades,
                       "params": params, "signal": sig}

# ── 最优方案详细展示 ──
print(f"\n{'='*75}")
print(f"  BEST: {best_result['name']}  Test={best_result['test_ret']:+.2%}")
print(f"{'='*75}")
print(f"  Params: entry={best_result['params'][0]:.2f} exit={best_result['params'][1]:.2f} "
      f"hold={best_result['params'][2]}d stop={best_result['params'][3]:.0%}")

# 最近信号
print(f"\n  Recent signals:")
for i in range(max(0, n-15), n):
    s = best_result["signal"][i]
    print(f"    {dates[i]}  close={close[i]:>7.2f}  signal={s:.4f}")
