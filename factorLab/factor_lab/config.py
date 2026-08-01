"""
统一配置管理模块
===============
所有可调参数集中于此，便于实验管理和参数搜索。
"""

from dataclasses import dataclass, field
from typing import List, Tuple, Optional


@dataclass
class DataConfig:
    """数据管线配置"""
    # --- 日期范围 ---
    train_start: str = "2023-01-01"
    train_end: str = "2024-12-31"
    val_start: str = "2025-01-01"
    val_end: str = "2026-05-01"

    # --- 频率: "monthly" | "weekly" ---
    frequency: str = "monthly"

    # --- 股票池 ---
    n_stocks: int = 500
    min_list_days: int = 375  # 次新股过滤阈值

    # --- 财报季跳过月份 ---
    skip_months: Tuple[int, ...] = (1, 4)

    # --- 停牌过滤 ---
    min_stocks_per_period: int = 50


@dataclass
class RegimeConfig:
    """Regime 检测配置"""
    # --- 决策树分裂参数 ---
    tree_max_depth: int = 2          # 最大深度 → 最多 2^depth 个 regime
    tree_min_samples_leaf: int = 300 # 每叶子最少样本数

    # --- KMeans 聚类参数 ---
    n_regimes: int = 3               # 强制 regime 数
    kmeans_n_init: int = 20          # KMeans 初始化次数

    # --- PCA 降维 ---
    pca_variance_ratio: float = 0.90 # 保留方差比例

    # --- Regime 画像特征 (用于 Regime 识别) ---
    regime_feature_keywords: List[str] = field(default_factory=lambda: [
        "vol_", "ret_", "ma5_ma20", "macdh", "bb_position", "rel_vol",
        "zscore_20", "skew_", "kurt_", "body_ratio", "dist_hh20", "dist_ll20",
        "atr_", "roc_", "hl_vol", "ret_range",
    ])


@dataclass
class GPMinerConfig:
    """遗传编程因子挖掘配置"""
    # --- 种群参数 ---
    population_size: int = 50
    n_generations: int = 25
    crossover_prob: float = 0.5
    mutation_prob: float = 0.2
    tournament_size: int = 3

    # --- 树结构约束 ---
    max_tree_height: int = 8
    init_min_depth: int = 1
    init_max_depth: int = 3  # Half-and-Half 初始化

    # --- 评估 ---
    min_ic_periods: int = 5          # 最少截面数
    min_samples_per_period: int = 30 # 每截面最少样本
    pooled_threshold: int = 15       # 少于该截面数则池化评估


@dataclass
class BacktestConfig:
    """回测配置"""
    prediction_days: int = 10        # 预测天数
    start_delay: int = 30            # 前N天不交易(积累窗口)
    position_threshold: float = 0.0  # 信号阈值
    annual_days: int = 252
    commission_rate: float = 0.0003  # 单边 0.03%


@dataclass
class FactorLabConfig:
    """总配置"""
    data: DataConfig = field(default_factory=DataConfig)
    regime: RegimeConfig = field(default_factory=RegimeConfig)
    gp: GPMinerConfig = field(default_factory=GPMinerConfig)
    backtest: BacktestConfig = field(default_factory=BacktestConfig)

    # --- 全局随机种子 ---
    random_seed: int = 42

    # --- 输出 ---
    verbose: bool = True


# ============================================================
# 预置配置方案
# ============================================================

def get_config(preset: str = "default") -> FactorLabConfig:
    """获取预置配置方案

    Args:
        preset: "default" | "fast" | "deep"

    Returns:
        FactorLabConfig 实例
    """
    cfg = FactorLabConfig()

    if preset == "fast":
        # 快速验证用
        cfg.data.train_start = "2024-01-01"
        cfg.data.frequency = "weekly"
        cfg.gp.population_size = 30
        cfg.gp.n_generations = 15
        cfg.regime.tree_max_depth = 1
        cfg.regime.tree_min_samples_leaf = 500

    elif preset == "deep":
        # 深度搜索用
        cfg.regime.tree_max_depth = 3
        cfg.gp.population_size = 100
        cfg.gp.n_generations = 50

    return cfg


# ============================================================
# 向量运算符集合 (供 deap GP 引擎使用)
# ============================================================
GP_OPERATORS = {
    "add": 2,      # v_add
    "sub": 2,      # v_sub
    "mul": 2,      # v_mul
    "div": 2,      # v_div
    "rank": 1,     # v_rank
    "abs": 1,      # v_abs
    "log": 1,      # v_log
    "neg": 1,      # v_neg
    "max": 2,      # v_max
    "min": 2,      # v_min
    "sgn": 1,      # v_sgn
}
