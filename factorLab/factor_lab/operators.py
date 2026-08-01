"""
向量运算符 & 基础工具模块
========================
供 deap GP 引擎使用的向量化运算符，以及通用滚动窗口、数据处理辅助函数。

所有运算符均为纯函数，接受/返回 np.ndarray，确保与 GP 引擎兼容。
"""

import numpy as np
import pandas as pd
from typing import Callable, Optional, Union


# ================================================================
# 向量运算符 (供 GP 引擎使用，必须为顶层普通函数)
# ================================================================

def v_add(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """向量加法 a + b"""
    return np.add(np.float64(a), np.float64(b))


def v_sub(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """向量减法 a - b"""
    return np.subtract(np.float64(a), np.float64(b))


def v_mul(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """向量乘法 a * b"""
    return np.multiply(np.float64(a), np.float64(b))


def v_div(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """安全除法 a / b，除零/无穷 → 0.0"""
    with np.errstate(divide='ignore', invalid='ignore'):
        result = np.divide(np.float64(a), np.float64(b))
        result = np.where(np.isfinite(result), result, 0.0)
    return result


def v_rank(x: np.ndarray) -> np.ndarray:
    """百分位排名 (pct=True)，等价于 cross-sectional rank"""
    x = np.float64(x).flatten()
    if len(x) < 2:
        return np.zeros_like(x)
    return pd.Series(x).rank(pct=True).values


def v_abs(x: np.ndarray) -> np.ndarray:
    """绝对值 |x|"""
    return np.abs(np.float64(x))


def v_log(x: np.ndarray) -> np.ndarray:
    """安全对数 log(max(|x|, 1e-8))"""
    return np.log(np.maximum(np.abs(np.float64(x)), 1e-8))


def v_neg(x: np.ndarray) -> np.ndarray:
    """取反 -x"""
    return -np.float64(x)


def v_max(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """逐元素最大值 max(a, b)"""
    return np.maximum(np.float64(a), np.float64(b))


def v_min(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """逐元素最小值 min(a, b)"""
    return np.minimum(np.float64(a), np.float64(b))


def v_sgn(x: np.ndarray) -> np.ndarray:
    """符号函数 sign(x) → {-1, 0, 1}"""
    return np.sign(np.float64(x))


# ================================================================
# 通用滚动窗口函数
# ================================================================

def rolling_apply(
    x: np.ndarray,
    window: int,
    func: Callable,
    min_periods: int = 1,
) -> np.ndarray:
    """
    对一维数组做滚动窗口计算（向量化版本）。

    Args:
        x: 输入一维数组
        window: 窗口大小
        func: 聚合函数，接受 raw array
        min_periods: 最少样本数

    Returns:
        np.ndarray，与 x 等长

    Examples:
        >>> rolling_apply(np.array([1,2,3,4,5]), 3, np.mean)
        array([1. , 1.5, 2. , 3. , 4. ])
    """
    return pd.Series(x).rolling(window, min_periods=min_periods).apply(
        func, raw=True
    ).values


def rolling_mean(x: np.ndarray, window: int) -> np.ndarray:
    """滚动均值"""
    return rolling_apply(x, window, np.mean)


def rolling_std(x: np.ndarray, window: int) -> np.ndarray:
    """滚动标准差"""
    return rolling_apply(x, window, np.std)


def rolling_max(x: np.ndarray, window: int) -> np.ndarray:
    """滚动最大值"""
    return rolling_apply(x, window, np.max)


def rolling_min(x: np.ndarray, window: int) -> np.ndarray:
    """滚动最小值"""
    return rolling_apply(x, window, np.min)


def rolling_skew(x: np.ndarray, window: int) -> np.ndarray:
    """滚动偏度"""
    return rolling_apply(x, window, lambda a: pd.Series(a).skew())


def rolling_kurt(x: np.ndarray, window: int) -> np.ndarray:
    """滚动峰度"""
    return rolling_apply(x, window, lambda a: pd.Series(a).kurt())


def ewm_mean(x: np.ndarray, span: int) -> np.ndarray:
    """指数加权移动平均"""
    return pd.Series(x).ewm(span=span, adjust=False).mean().values


def rolling_sum(x: np.ndarray, window: int) -> np.ndarray:
    """滚动求和"""
    return pd.Series(x).rolling(window, min_periods=1).sum().values


def rolling_corr(a: np.ndarray, b: np.ndarray, window: int) -> np.ndarray:
    """两个序列的滚动皮尔逊相关系数"""
    return pd.Series(a).rolling(window, min_periods=3).corr(pd.Series(b)).values


def delta(x: np.ndarray, period: int) -> np.ndarray:
    """N日差分: x[t] - x[t-N]"""
    result = np.full_like(x, np.nan, dtype=np.float64)
    result[period:] = x[period:] - x[:-period]
    return result


def delay(x: np.ndarray, period: int) -> np.ndarray:
    """N日滞后: x[t-N]"""
    result = np.full_like(x, np.nan, dtype=np.float64)
    result[period:] = x[:-period]
    return result


def decay_linear(x: np.ndarray, window: int) -> np.ndarray:
    """线性衰减加权平均: 最近权重最高, 线性递减"""
    w = np.arange(1, window + 1, dtype=np.float64)
    w = w / w.sum()
    result = np.full_like(x, np.nan, dtype=np.float64)
    for i in range(window - 1, len(x)):
        result[i] = np.dot(x[i - window + 1:i + 1], w)
    return result


def rolling_slope(x: np.ndarray, window: int) -> np.ndarray:
    """滚动线性回归斜率 (最小二乘)"""
    result = np.full_like(x, np.nan, dtype=np.float64)
    t = np.arange(window, dtype=np.float64)
    t_mean = t.mean()
    denom = ((t - t_mean) ** 2).sum()
    if denom < 1e-12:
        return result
    for i in range(window - 1, len(x)):
        y = x[i - window + 1:i + 1]
        result[i] = np.dot(t - t_mean, y - y.mean()) / denom
    return result


def ts_rank(x: np.ndarray, window: int) -> np.ndarray:
    """滚动分位排名: 过去 window 天中今天是第几"""
    result = np.full_like(x, np.nan, dtype=np.float64)
    for i in range(window - 1, len(x)):
        segment = x[i - window + 1:i + 1]
        valid = np.isfinite(segment)
        if valid.sum() < 2:
            result[i] = 0.5
        else:
            result[i] = (segment[valid] <= segment[-1]).mean()
    return result


def scale(x: np.ndarray) -> np.ndarray:
    """Min-Max 归一化到 [0, 1]"""
    xmin, xmax = np.nanmin(x), np.nanmax(x)
    if xmax - xmin < 1e-12:
        return np.zeros_like(x)
    return (x - xmin) / (xmax - xmin)


def safe_div(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """安全除法 a/b, 除零→0"""
    with np.errstate(divide='ignore', invalid='ignore'):
        result = np.divide(np.float64(a), np.float64(b))
        result = np.where(np.isfinite(result), result, 0.0)
    return result


# ================================================================
# 矩阵处理工具
# ================================================================

def safe_nan_to_num(
    x: np.ndarray,
    nan: float = 0.0,
    posinf: float = 1e8,
    neginf: float = -1e8,
) -> np.ndarray:
    """安全替换 NaN/Inf"""
    return np.nan_to_num(np.asarray(x, dtype=np.float64), nan=nan, posinf=posinf, neginf=neginf)


def finite_mask(*arrays: np.ndarray) -> np.ndarray:
    """计算多个数组共有的有限值掩码 (逻辑与)"""
    mask = np.ones(len(arrays[0]), dtype=bool)
    for arr in arrays:
        mask = mask & np.isfinite(arr)
    return mask


def cross_sectional_zscore(x: np.ndarray) -> np.ndarray:
    """截面标准化 (Z-Score)，忽略 NaN"""
    mu = np.nanmean(x)
    sd = np.nanstd(x)
    if sd < 1e-12:
        return np.zeros_like(x)
    return (x - mu) / sd


def cross_sectional_rank(x: np.ndarray) -> np.ndarray:
    """截面百分位排名 → [0, 1]"""
    valid = np.isfinite(x)
    result = np.full_like(x, np.nan, dtype=np.float64)
    if valid.sum() < 2:
        return result
    result[valid] = pd.Series(x[valid]).rank(pct=True).values
    return result


def pairwise_correlation(a: np.ndarray, b: np.ndarray) -> float:
    """计算两个向量的皮尔逊相关系数（忽略 NaN）"""
    mask = np.isfinite(a) & np.isfinite(b)
    if mask.sum() < 3:
        return np.nan
    return np.corrcoef(a[mask], b[mask])[0, 1]


def spearman_correlation(a: np.ndarray, b: np.ndarray) -> float:
    """计算两个向量的斯皮尔曼等级相关系数"""
    mask = np.isfinite(a) & np.isfinite(b)
    if mask.sum() < 5:
        return np.nan
    from scipy import stats as ss
    return ss.spearmanr(a[mask], b[mask])[0]


# ================================================================
# 算子注册表 (供 GP 引擎自动化)
# ================================================================

OPERATOR_REGISTRY = {
    "v_add":  (v_add,  2),
    "v_sub":  (v_sub,  2),
    "v_mul":  (v_mul,  2),
    "v_div":  (v_div,  2),
    "v_rank": (v_rank, 1),
    "v_abs":  (v_abs,  1),
    "v_log":  (v_log,  1),
    "v_neg":  (v_neg,  1),
    "v_max":  (v_max,  2),
    "v_min":  (v_min,  2),
    "v_sgn":  (v_sgn,  1),
}
