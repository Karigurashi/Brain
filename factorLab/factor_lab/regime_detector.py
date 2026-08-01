"""
Regime（市场状态）检测模块
========================
提供三种 Regime 检测方法：

  1. DecisionTreeRegressorRegime  — 决策树回归分裂（PS-Tree 风格），用于多股票截面
  2. KMeansRegimeDetector         — KMeans+PCA+决策树，用于单股时序
  3. RegimeExitAnalyzer           — 分析特定 Regime 的退出规律

用法:
    from factor_lab.regime_detector import KMeansRegimeDetector, RegimeExitAnalyzer
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from factor_lab.config import RegimeConfig
from factor_lab.operators import safe_nan_to_num


# ================================================================
# 输出数据结构
# ================================================================

@dataclass
class RegimePath:
    """单个 Regime 的决策路径"""
    leaf_id: int
    sequence_id: int            # R1, R2, R3...
    conditions: List[Tuple[str, float, bool]]  # [(feature, threshold, is_left), ...]
    n_samples: int = 0
    description: str = ""

    def condition_string(self) -> str:
        """生成可读的条件表达式，如 'vol_20d <= 0.15 AND bb_position > -0.58'"""
        parts = []
        for fn, th, is_left in self.conditions:
            op = "<=" if is_left else ">"
            parts.append(f"{fn} {op} {th:.4g}")
        return " AND ".join(parts)


@dataclass
class RegimeResult:
    """Regime 检测完整结果"""
    labels: np.ndarray                    # regime 标签 [n_samples]
    n_regimes: int                        # regime 数量
    paths: List[RegimePath]               # 各 regime 的决策路径
    feature_names: List[str]              # 用于分裂的特征名
    regime_stats: Dict[int, Dict] = field(default_factory=dict)  # per-regime 统计


# ================================================================
# 方案一: 决策树回归分裂 (PS-Tree 风格)
# ================================================================

class TreeRegimeDetector:
    """
    基于决策树回归的分裂式 Regime 检测。

    原理: 用 sklearn DecisionTreeRegressor 对 (特征, 收益) 拟合，
         树的叶子节点即为自动发现的 Regime。
         每个叶子对应一条从根到叶的分裂路径（可解释规则）。

    适用场景: 多股票截面数据，特征 + 前向收益

    Example:
        detector = TreeRegimeDetector(RegimeConfig(tree_max_depth=2, tree_min_samples_leaf=300))
        result = detector.fit_predict(X_train, y_train, feature_names)
    """

    def __init__(self, config: Optional[RegimeConfig] = None):
        self.config = config or RegimeConfig()

    def fit_predict(
        self,
        X: np.ndarray,
        y: np.ndarray,
        feature_names: List[str],
    ) -> RegimeResult:
        """
        训练决策树并返回 Regime 划分。

        Args:
            X: 特征矩阵 (n_samples, n_features)，须为有限值
            y: 目标值 (n_samples,)，如 forward return
            feature_names: 特征名列表

        Returns:
            RegimeResult
        """
        from sklearn.tree import DecisionTreeRegressor

        dtree = DecisionTreeRegressor(
            max_depth=self.config.tree_max_depth,
            min_samples_leaf=self.config.tree_min_samples_leaf,
            random_state=42,
        )
        dtree.fit(X, y)

        tree = dtree.tree_
        paths = self._extract_paths(tree, feature_names)
        n_regimes = len(paths)

        # 分配序号
        for i, p in enumerate(paths):
            p.sequence_id = i + 1

        # 预测标签
        leaf_ids = dtree.apply(X).flatten()
        labels = np.zeros(len(X), dtype=int)
        for leaf_id, path in [(p.leaf_id, p) for p in paths]:
            labels[leaf_ids == leaf_id] = path.sequence_id - 1

        # 统计
        regime_stats = {}
        for path in paths:
            mask = leaf_ids == path.leaf_id
            path.n_samples = mask.sum()
            regime_stats[path.sequence_id] = {
                "leaf_id": path.leaf_id,
                "n_samples": path.n_samples,
                "mean_target": float(np.mean(y[mask])) if mask.sum() > 0 else 0.0,
                "conditions": path.condition_string(),
            }

        return RegimeResult(
            labels=labels,
            n_regimes=n_regimes,
            paths=paths,
            feature_names=feature_names,
            regime_stats=regime_stats,
        )

    @staticmethod
    def _extract_paths(tree, feature_names: List[str]) -> List[RegimePath]:
        """递归提取从根到每个叶子的决策路径"""
        paths = []

        def traverse(node_id: int, conditions: List[Tuple[str, float, bool]]):
            if tree.children_left[node_id] == tree.children_right[node_id]:
                # 叶子节点
                paths.append(RegimePath(
                    leaf_id=node_id,
                    sequence_id=0,
                    conditions=list(conditions),
                ))
                return
            feat_name = feature_names[tree.feature[node_id]]
            thresh = tree.threshold[node_id]
            traverse(tree.children_left[node_id],
                     conditions + [(feat_name, thresh, True)])   # <=
            traverse(tree.children_right[node_id],
                     conditions + [(feat_name, thresh, False)])  # >

        traverse(0, [])
        return paths


# ================================================================
# 方案二: KMeans + PCA + 决策树 (单股时序)
# ================================================================

class KMeansRegimeDetector:
    """
    KMeans+PCA+决策树 三级 Regime 检测。

    流程:
      1. PCA 降维 (保留指定方差比例)
      2. KMeans 聚类 → 无监督 Regime 标签
      3. 决策树分类器 学习聚类边界 → 输出可解释规则

    适用场景: 单股时序数据，仅特征（无目标收益）

    Example:
        detector = KMeansRegimeDetector(RegimeConfig(n_regimes=3))
        result = detector.fit_predict(X_train, feature_names, train_mask)
    """

    def __init__(self, config: Optional[RegimeConfig] = None):
        self.config = config or RegimeConfig()
        self.pca_ = None
        self.kmeans_ = None
        self.dt_ = None

    def _select_regime_features(
        self,
        feature_names: List[str],
    ) -> Tuple[List[str], np.ndarray]:
        """
        从全部特征中筛选用于 Regime 检测的核心特征。

        Returns:
            (selected_names, column_indices)
        """
        keywords = self.config.regime_feature_keywords
        selected = []
        indices = []
        for i, name in enumerate(feature_names):
            if any(kw in name for kw in keywords):
                selected.append(name)
                indices.append(i)
        return selected, np.array(indices)

    def fit_predict(
        self,
        X: np.ndarray,
        feature_names: List[str],
        train_mask: np.ndarray,
    ) -> RegimeResult:
        """
        Args:
            X: 特征矩阵 (n_samples, n_features)
            feature_names: 全量特征名
            train_mask: 训练集 bool 掩码

        Returns:
            RegimeResult
        """
        from sklearn.cluster import KMeans
        from sklearn.decomposition import PCA
        from sklearn.tree import DecisionTreeClassifier

        # 1. 筛选 Regime 特征
        regime_feat_names, regime_idx = self._select_regime_features(feature_names)
        X_regime = X[:, regime_idx]

        # 2. PCA 降维
        self.pca_ = PCA(n_components=self.config.pca_variance_ratio,
                        random_state=42)
        X_pca_train = self.pca_.fit_transform(X_regime[train_mask])
        X_pca_all = self.pca_.transform(X_regime)

        # 3. KMeans 聚类
        self.kmeans_ = KMeans(
            n_clusters=self.config.n_regimes,
            n_init=self.config.kmeans_n_init,
            random_state=42,
        )
        cluster_labels = self.kmeans_.fit_predict(X_pca_all)

        # 4. 决策树学习边界
        self.dt_ = DecisionTreeClassifier(
            max_depth=3,
            min_samples_leaf=10,
            random_state=42,
        )
        self.dt_.fit(X_regime[train_mask], cluster_labels[train_mask])
        final_labels = self.dt_.predict(X_regime)

        # 5. 构建输出
        K = self.config.n_regimes
        paths = []
        for ri in range(K):
            paths.append(RegimePath(
                leaf_id=ri,
                sequence_id=ri,
                conditions=[],  # 决策树规则需从 export_text 提取
                description=self._describe_regime(final_labels, ri, X),
            ))

        # 统计（仅计数，收益统计由上层 RegimeSplitter 负责）
        regime_stats = {}
        for ri in range(K):
            mask = final_labels == ri
            regime_stats[ri] = {
                "n_samples": int(mask.sum()),
            }

        return RegimeResult(
            labels=final_labels,
            n_regimes=K,
            paths=paths,
            feature_names=regime_feat_names,
            regime_stats=regime_stats,
        )

    @staticmethod
    def _describe_regime(labels: np.ndarray, regime_id: int,
                         X: np.ndarray) -> str:
        """生成 Regime 文字画像"""
        mask = labels == regime_id
        n = mask.sum()
        if n < 5:
            return f"R{regime_id}: {n} samples (insufficient)"
        vol = np.nanmean(np.abs(np.diff(X[mask], axis=0)))
        if vol > 0.04:
            tag = "[高波动]"
        elif vol < 0.015:
            tag = "[低波动]"
        else:
            tag = "[中等波动]"
        return f"R{regime_id}: {n} 天 {tag} vol≈{vol:.4f}"

    def export_rules(self) -> str:
        """导出可解释的决策树规则"""
        if self.dt_ is None:
            return "未训练，请先调用 fit_predict()"
        from sklearn.tree import export_text
        _, regime_feat_names = self._select_regime_features([])
        # 实际使用时需要传入正确的 feature_names
        return "决策树规则: 请使用 detector.dt_ 直接访问"


# ================================================================
# Regime 退出分析器 (源自 r2_exit.py)
# ================================================================

class RegimeExitAnalyzer:
    """
    分析特定 Regime 的退出规律。

    功能:
      - 找出一只股票历史上从目标 Regime 退出的所有时点
      - 分析触发退出的因素（波动率跳升 / 价格破位 / 单日波动）
      - 评估当前距离退出的远近
      - 统计退出条件阈值

    Example:
        analyzer = RegimeExitAnalyzer()
        exit_report = analyzer.analyze(
            regime_labels=labels,
            features=feature_set.features,
            dates=dates,
            target_regime=2,
            exit_conditions={"vol_20d": (0.15, ">"), "bb_position": (-0.58, "<=")},
        )
    """

    def __init__(self):
        self.exit_points: List[Dict] = []
        self.blocks: List[Tuple[int, int]] = []

    def analyze(
        self,
        regime_labels: np.ndarray,
        features: Dict[str, np.ndarray],
        dates: List[str],
        target_regime: int,
        exit_conditions: Optional[Dict[str, Tuple[float, str]]] = None,
        verbose: bool = True,
    ) -> Dict:
        """
        分析目标 Regime 的退出规律。

        Args:
            regime_labels: Regime 标签序列 [n]
            features: 特征字典 (feature_name → array[n])
            dates: 日期序列 [n]
            target_regime: 要分析的目标 Regime 编号
            exit_conditions: 退出条件 {feature: (threshold, operator)}
                             如 {"vol_20d": (0.15, ">"), "bb_position": (-0.58, "<=")}
            verbose: 是否打印报告

        Returns:
            包含 exit_points、blocks、current_status 等信息的字典
        """
        n = len(regime_labels)
        target_mask = regime_labels == target_regime

        # 1. 找退出点 (target → non-target)
        self.exit_points = []
        for i in range(1, n):
            if regime_labels[i - 1] == target_regime and regime_labels[i] != target_regime:
                exit_info = {
                    "index": i,
                    "date": dates[i] if i < len(dates) else "?",
                    "exit_price": features.get("close", [0] * n)[i] if "close" in features else 0,
                    "next_regime": int(regime_labels[i]),
                    "triggers": self._detect_triggers(features, i),
                }
                self.exit_points.append(exit_info)

        # 2. 找连贯区块
        self.blocks = self._find_blocks(target_mask)

        # 3. 当前状态
        current_status = self._assess_current(
            regime_labels, features, dates, target_regime, exit_conditions
        )

        # 4. 打印报告
        if verbose and self.exit_points:
            self._print_report(current_status)

        return {
            "exit_points": self.exit_points,
            "blocks": self.blocks,
            "current_status": current_status,
            "n_exits": len(self.exit_points),
            "avg_block_duration": (
                np.mean([end - start for start, end in self.blocks if end - start >= 3])
                if self.blocks else 0
            ),
        }

    def _detect_triggers(self, features: Dict[str, np.ndarray],
                         idx: int) -> List[str]:
        """检测单个退出点的触发因素"""
        triggers = []

        if "vol_20d" in features:
            v_now = features["vol_20d"][idx]
            v_prev = features["vol_20d"][idx - 1]
            if v_now > v_prev * 1.3:
                triggers.append(f"波动率跳升 {v_prev:.4f}→{v_now:.4f}")

        if "bb_position" in features:
            bb_now = features["bb_position"][idx]
            bb_prev = features["bb_position"][idx - 1]
            if bb_now < bb_prev - 0.1:
                triggers.append(f"价格破位 bb={bb_now:.2f}")

        if "ret_1d" in features:
            ret = features["ret_1d"][idx]
            if abs(ret) > 0.05:
                triggers.append(f"单日波动 {ret:+.1%}")

        if "rel_vol" in features:
            rv = features["rel_vol"][idx]
            if rv > 2.0:
                triggers.append(f"放量 {rv:.1f}x")

        return triggers

    @staticmethod
    def _find_blocks(mask: np.ndarray) -> List[Tuple[int, int]]:
        """找到连续的 True 区块 (start, end) — end 为 exclusive"""
        blocks = []
        in_block = False
        start = 0
        for i in range(len(mask)):
            if mask[i] and not in_block:
                start = i
                in_block = True
            elif not mask[i] and in_block:
                blocks.append((start, i))
                in_block = False
        if in_block:
            blocks.append((start, len(mask)))
        return blocks

    def _assess_current(
        self,
        regime_labels: np.ndarray,
        features: Dict[str, np.ndarray],
        dates: List[str],
        target_regime: int,
        exit_conditions: Optional[Dict[str, Tuple[float, str]]],
    ) -> Dict:
        """评估当前状态：是否在目标 Regime，距退出多远"""
        n = len(regime_labels)
        current_regime = int(regime_labels[-1])
        in_target = current_regime == target_regime

        status: Dict = {
            "current_date": dates[-1] if dates else "?",
            "current_regime": current_regime,
            "in_target": in_target,
            "current_price": features.get("close", [0] * n)[-1] if "close" in features else 0,
            "distance_to_exit": {},
        }

        if in_target:
            # 已持续天数
            recent_mask = regime_labels[-20:] == target_regime
            status["recent_days_in_regime"] = int(recent_mask.sum())
            status["continuous_days"] = self._continuous_days(regime_labels, target_regime)

            # 距退出条件多远
            if exit_conditions:
                for feat, (thresh, op) in exit_conditions.items():
                    if feat in features:
                        current_val = float(features[feat][-1])
                        if op == ">":
                            gap = thresh - current_val
                            status["distance_to_exit"][feat] = {
                                "current": current_val,
                                "threshold": thresh,
                                "gap": gap,
                                "ratio": thresh / (current_val + 1e-8),
                            }
                        elif op == "<=":
                            gap = current_val - thresh
                            status["distance_to_exit"][feat] = {
                                "current": current_val,
                                "threshold": thresh,
                                "gap": gap,
                                "ratio": current_val / (thresh + 1e-8),
                            }

        return status

    @staticmethod
    def _continuous_days(labels: np.ndarray, target: int) -> int:
        """当前连续在目标 Regime 中的天数"""
        count = 0
        for i in range(len(labels) - 1, -1, -1):
            if labels[i] == target:
                count += 1
            else:
                break
        return count

    def _print_report(self, status: Dict):
        """打印退出分析报告"""
        print(f"\n{'='*65}")
        print(f"  Regime 退出规律分析")
        print(f"{'='*65}")
        print(f"  退出次数: {len(self.exit_points)}")

        if self.exit_points:
            print(f"\n  {'日期':<12s} {'退出价':>8s} {'进入区':>8s}   {'触发因素'}")
            print(f"  {'-'*55}")
            for ep in self.exit_points[:10]:  # 只显示前10条
                triggers = ", ".join(ep["triggers"]) if ep["triggers"] else "缓慢过渡"
                print(f"  {ep['date']:<12s} {ep['exit_price']:>8.2f} "
                      f"  R{ep['next_regime']:<7}   {triggers}")
            if len(self.exit_points) > 10:
                print(f"  ... 共 {len(self.exit_points)} 次退出，仅显示前10条")

        if self.blocks:
            real_blocks = [b for b in self.blocks if b[1] - b[0] >= 3]
            if real_blocks:
                durations = [end - start for start, end in real_blocks]
                print(f"\n  历史持续天数(≥3天): 均值={np.mean(durations):.0f}天 "
                      f"中位数={np.median(durations):.0f}天 "
                      f"最长={np.max(durations)}天")
                print(f"  当前已持续: {status.get('continuous_days', '?')}天")

        print(f"\n  当前状态:")
        print(f"    日期: {status['current_date']}")
        print(f"    价格: {status['current_price']:.2f}")
        if status.get("in_target"):
            print(f"    已在目标 Regime 中 (连续 {status['continuous_days']} 天)")
            for feat, info in status.get("distance_to_exit", {}).items():
                direction = "↑ 接近" if info["gap"] < 0 else "↓ 远离"
                print(f"    {feat}: {info['current']:.4f} (阈值={info['threshold']}) {direction}")
        else:
            print(f"    当前不在目标 Regime (Regime={status['current_regime']})")
