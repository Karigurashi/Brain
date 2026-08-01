"""
FeatureBuilder - Alpha158 风格特征工厂
========================================
从 OHLCV 6 个基础字段, 用 19 个算子 x 5 个时间窗口, 生成 50+ 衍生特征。
"""
import numpy as np
import pandas as pd
from factor_lab.operators import (
    rolling_mean, rolling_std, rolling_skew, rolling_kurt,
    rolling_max, rolling_min, rolling_sum, rolling_corr,
    delta, delay, decay_linear, rolling_slope, ts_rank, safe_div,
)

BASE_FIELDS = ["open", "high", "low", "close", "volume", "vwap"]
WINDOWS = [5, 10, 20, 30, 60]

DERIVED_SERIES = {
    "log_ret":     lambda d: np.r_[0.0, np.log(d["close"][1:] / d["close"][:-1])],
    "high_low":    lambda d: d["high"] - d["low"],
    "close_open":  lambda d: d["close"] - d["open"],
    "vr":          lambda d: safe_div(d["volume"], rolling_mean(d["volume"], 20)),
    "atr":         lambda d: rolling_mean(np.maximum(
                        d["high"] - d["low"],
                        np.maximum(np.abs(d["high"] - np.roll(d["close"], 1)),
                                   np.abs(d["low"] - np.roll(d["close"], 1)))), 14),
}

# (名称, 算子, [字段], "w"=需窗口 / ""=不需要)
FEATURE_RULES = [
    # === 滚动统计 ===
    ("{f}_mean_{w}",    rolling_mean,   ["open","high","low","close","volume","vwap"], "w"),
    ("{f}_std_{w}",     rolling_std,    ["open","high","low","close","volume","vwap"], "w"),
    ("{f}_skew_{w}",    rolling_skew,   ["close","volume"], "w"),
    ("{f}_kurt_{w}",    rolling_kurt,   ["close","volume"], "w"),
    ("{f}_max_{w}",     rolling_max,    ["high","close","volume"], "w"),
    ("{f}_min_{w}",     rolling_min,    ["low","close","volume"], "w"),
    ("{f}_sum_{w}",     rolling_sum,    ["volume"], "w"),
    # === 动量/差分 ===
    ("{f}_delta_{w}",   delta,          ["close","volume"], "w"),
    ("{f}_delay_{w}",   delay,          ["close"], "w"),
    ("{f}_decay_{w}",   decay_linear,   ["close"], "w"),
    ("{f}_slope_{w}",   rolling_slope,  ["close","volume"], "w"),
    # === 排序/归一化 ===
    ("{f}_tsrank_{w}",  ts_rank,        ["close","volume"], "w"),
    # === 衍生序列 ===
    ("logret_mean_{w}",     rolling_mean,   ["log_ret"], "w"),
    ("logret_std_{w}",      rolling_std,    ["log_ret"], "w"),
    ("logret_skew_{w}",     rolling_skew,   ["log_ret"], "w"),
    ("logret_kurt_{w}",     rolling_kurt,   ["log_ret"], "w"),
    ("logret_delta_{w}",    delta,          ["log_ret"], "w"),
    ("logret_decay_{w}",    decay_linear,   ["log_ret"], "w"),
    ("logret_slope_{w}",    rolling_slope,  ["log_ret"], "w"),
    ("spread_mean_{w}",     rolling_mean,   ["high_low"], "w"),
    ("spread_std_{w}",      rolling_std,    ["high_low"], "w"),
    ("spread_max_{w}",      rolling_max,    ["high_low"], "w"),
    ("body_mean_{w}",       rolling_mean,   ["close_open"], "w"),
    ("body_std_{w}",        rolling_std,    ["close_open"], "w"),
    ("vr_mean_{w}",         rolling_mean,   ["vr"], "w"),
    ("vr_max_{w}",          rolling_max,    ["vr"], "w"),
    ("atr_mean_{w}",        rolling_mean,   ["atr"], "w"),
    # === 比值 (无窗口) ===
    ("atr_ratio",           None,           [["atr","close"]], ""),
    # === 交叉特征 ===
    ("close_vol_corr_{w}",  None,           [["close","volume"]], "w"),
    ("high_low_corr_{w}",   None,           [["high","low"]], "w"),
]


class FeatureBuilder:
    """Alpha158 风格特征生成器"""

    def __init__(self, windows: list = None, verbose: bool = True):
        self.windows = windows or WINDOWS
        self.verbose = verbose
        self.n_features = 0

    def build(self, open_: np.ndarray, high: np.ndarray, low: np.ndarray,
              close: np.ndarray, volume: np.ndarray) -> dict:
        """从 OHLCV 生成全部衍生特征"""
        data = {
            "open": open_, "high": high, "low": low,
            "close": close, "volume": volume,
            "vwap": safe_div(np.float64(high + low + close) * volume,
                             np.float64(volume * 3 + 1e-8)),
        }
        for name, fn in DERIVED_SERIES.items():
            data[name] = fn(data)

        features = {}
        total = 0

        for name_tpl, _func, fields, wmode in FEATURE_RULES:
            for w in (self.windows if wmode == "w" else [None]):
                for f in fields:
                    # 名称
                    if isinstance(f, list):
                        fname = name_tpl.format(f=f[0]+"_"+f[1], w=w)
                    else:
                        fname = name_tpl.format(f=f, w=w)

                    # 计算
                    if isinstance(f, list):
                        a, b = data[f[0]], data[f[1]]
                        if "corr" in name_tpl:
                            result = rolling_corr(np.float64(a), np.float64(b), w)
                        elif "ratio" in name_tpl:
                            result = safe_div(np.float64(a), np.float64(b))
                        else:
                            result = np.zeros_like(a)
                    elif wmode == "w":
                        result = _func(np.float64(data[f]), w)
                    else:
                        result = _func(np.float64(data[f]))

                    result = np.nan_to_num(np.float64(result), nan=0.0)
                    features[fname] = result
                    total += 1

        self.n_features = total
        if self.verbose:
            print(f"[FeatureBuilder] {len(BASE_FIELDS)} fields → {total} features "
                  f"(windows: {self.windows})")
        return features

    def to_dataframe(self, features: dict) -> pd.DataFrame:
        return pd.DataFrame(features)


def build_features(open_, high, low, close, volume, windows=None):
    return FeatureBuilder(windows=windows).build(open_, high, low, close, volume)
