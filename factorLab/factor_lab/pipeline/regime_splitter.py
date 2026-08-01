"""
Pipeline Stage 3: RegimeSplitter
================================
在训练集上检测市场 Regime，并将标签映射到全量数据。

流程:
  1. 仅用训练集特征做 Regime 检测（严格避免数据泄露）
  2. 决策树或 KMeans 自动发现 Regime 边界
  3. 将 Regime 标签映射到训练/验证/测试全量数据
  4. 输出每个 Regime 的可解释规则 + 统计画像

依赖: factor_lab.regime_detector
"""

import numpy as np
import pandas as pd
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass, field


@dataclass
class RegimeSplitResult:
    """Regime 拆分结果"""
    regime_labels: np.ndarray          # [n] 每样本的 Regime ID
    n_regimes: int                     # Regime 数量
    regime_stats: Dict[int, Dict]      # per-regime 统计
    regime_paths: List                 # 决策路径（可解释规则）
    feature_names: List[str]           # 用于检测的特征名
    train_regime_mask: Dict[int, np.ndarray]  # 训练集内各 regime 的 bool 掩码
    val_regime_mask: Dict[int, np.ndarray]
    test_regime_mask: Dict[int, np.ndarray]


class RegimeSplitter:
    """
    训练集 Regime 检测 + 全量标签映射。

    支持两种模式:
      - "tree": 决策树回归分裂（PS-Tree 风格，需要目标收益）
      - "kmeans": KMeans+PCA+决策树（无监督，仅需特征）

    Example:
        splitter = RegimeSplitter(method="kmeans", n_regimes=4)
        result = splitter.fit_predict(
            X, feature_names, target, train_mask, val_mask, test_mask
        )
    """

    def __init__(
        self,
        method: str = "kmeans",
        n_regimes: int = 4,
        tree_max_depth: int = 2,
        tree_min_samples_leaf: int = 60,
        pca_variance_ratio: float = 0.90,
        random_seed: int = 42,
    ):
        """
        Args:
            method: "tree" | "kmeans"
            n_regimes: 目标 Regime 数量
            tree_max_depth: 决策树最大深度
            tree_min_samples_leaf: 叶子最少样本数
            pca_variance_ratio: PCA 保留方差比例
            random_seed: 随机种子
        """
        self.method = method
        self.n_regimes = n_regimes
        self.tree_max_depth = tree_max_depth
        self.tree_min_samples_leaf = tree_min_samples_leaf
        self.pca_variance_ratio = pca_variance_ratio
        self.random_seed = random_seed

        self.detector_ = None

    def fit_predict(
        self,
        X: np.ndarray,
        feature_names: List[str],
        target: np.ndarray,
        train_mask: np.ndarray,
        val_mask: np.ndarray,
        test_mask: np.ndarray,
        verbose: bool = True,
    ) -> RegimeSplitResult:
        """
        在训练集上检测 Regime，映射到全量。

        Args:
            X: 特征矩阵 [n, n_features]，已标准化
            feature_names: 特征名列表
            target: 目标收益 [n]
            train_mask / val_mask / test_mask: 三段掩码
            verbose: 打印进度

        Returns:
            RegimeSplitResult
        """
        from factor_lab.regime_detector import (
            KMeansRegimeDetector, TreeRegimeDetector,
        )
        from factor_lab.config import RegimeConfig

        if self.method == "tree":
            detector = TreeRegimeDetector(RegimeConfig(
                tree_max_depth=self.tree_max_depth,
                tree_min_samples_leaf=self.tree_min_samples_leaf,
            ))
            result = detector.fit_predict(
                X[train_mask], target[train_mask], feature_names,
            )

            # 决策树只能对训练集打标签 —— 但我们可以用 predict_on 逻辑
            # 对于 tree 方法，这里简化：用训练集的叶子规则推断全量
            # 实际工程中建议用 kmeans 方法（更稳定）
            from sklearn.tree import DecisionTreeClassifier
            dt = DecisionTreeClassifier(
                max_depth=self.tree_max_depth,
                min_samples_leaf=self.tree_min_samples_leaf,
                random_state=self.random_seed,
            )
            dt.fit(X[train_mask], result.labels)
            all_labels = dt.predict(X)

        else:
            # KMeans 方法
            detector = KMeansRegimeDetector(RegimeConfig(
                n_regimes=self.n_regimes,
                tree_max_depth=self.tree_max_depth,
                tree_min_samples_leaf=self.tree_min_samples_leaf,
                pca_variance_ratio=self.pca_variance_ratio,
            ))
            result = detector.fit_predict(X, feature_names, train_mask)
            all_labels = result.labels

        self.detector_ = detector

        # 统计
        regime_stats = {}
        train_regime_mask = {}
        val_regime_mask = {}
        test_regime_mask = {}

        for ri in range(result.n_regimes):
            rm = all_labels == ri
            tgt_train = target[train_mask & rm]
            tgt_val = target[val_mask & rm]
            tgt_test = target[test_mask & rm]
            regime_stats[ri] = {
                "n_total": int(rm.sum()),
                "n_train": int(rm[train_mask].sum()),
                "n_val": int(rm[val_mask].sum()),
                "n_test": int(rm[test_mask].sum()),
                "mean_target_train": float(np.nanmean(tgt_train)) if len(tgt_train) > 0 else 0.0,
                "mean_target_val": float(np.nanmean(tgt_val)) if len(tgt_val) > 0 else 0.0,
                "mean_target_test": float(np.nanmean(tgt_test)) if len(tgt_test) > 0 else 0.0,
            }
            train_regime_mask[ri] = train_mask & rm
            val_regime_mask[ri] = val_mask & rm
            test_regime_mask[ri] = test_mask & rm

        if verbose:
            self._print_report(result.n_regimes, regime_stats, result.paths)

        return RegimeSplitResult(
            regime_labels=all_labels,
            n_regimes=result.n_regimes,
            regime_stats=regime_stats,
            regime_paths=result.paths,
            feature_names=result.feature_names,
            train_regime_mask=train_regime_mask,
            val_regime_mask=val_regime_mask,
            test_regime_mask=test_regime_mask,
        )

    @staticmethod
    def _print_report(n_regimes: int, stats: Dict, paths: List):
        """打印 Regime 划分报告"""
        print(f"\n{'='*60}")
        print(f"  Regime 检测结果: 发现 {n_regimes} 个市场状态")
        print(f"{'='*60}")

        # 按训练集样本量排序
        sorted_regimes = sorted(stats.items(),
                                key=lambda x: x[1]["n_train"], reverse=True)
        for ri, s in sorted_regimes:
            tgt = s["mean_target_train"]
            tag = "UP" if tgt > 0.002 else ("DN" if tgt < -0.002 else "--")
            print(f"  Regime {ri}: {tag} train={s['n_train']:>4d}天  "
                  f"val={s['n_val']:>4d}天  test={s['n_test']:>4d}天  "
                  f"mean_ret={tgt:+.4f}")

        # 如果有决策路径，打印规则
        if paths:
            for p in paths:
                cond = getattr(p, 'condition_string', lambda: '')()
                if cond:
                    print(f"    |_ R{p.sequence_id}: {cond}")
        print()
