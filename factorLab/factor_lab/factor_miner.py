"""
因子挖掘引擎模块
===============
双引擎架构：

  1. GPFactorMiner   — 遗传编程(GP)自动搜索因子公式
  2. TemplateMiner    — 知识引导模板因子评估

用法:
    from factor_lab.factor_miner import GPFactorMiner, TemplateMiner
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Tuple, Optional, Callable
from dataclasses import dataclass, field
import random
import operator
import warnings

from factor_lab.config import GPMinerConfig
from factor_lab.operators import (
    v_add, v_sub, v_mul, v_div, v_rank, v_abs, v_log, v_neg,
    v_max, v_min, v_sgn, pairwise_correlation, spearman_correlation,
    safe_nan_to_num, cross_sectional_rank,
)

warnings.filterwarnings('ignore')


# ================================================================
# 因子挖掘结果
# ================================================================

@dataclass
class FactorResult:
    """单个因子挖掘结果"""
    name: str
    expression: str                    # 公式表达式
    category: str = ""                 # 类别: rev/trend/lowvol/universal
    logic_description: str = ""        # 逻辑说明
    train_ic: float = 0.0
    test_ic: float = 0.0
    ic_std: float = 0.0               # IC 标准差
    icir: float = 0.0                 # Information Coefficient IR
    ic_win_rate: float = 0.0
    score: float = 0.0                # 综合得分
    factor_values: Optional[np.ndarray] = None  # 因子值序列
    regime_id: Optional[int] = None   # 所属 Regime

    def __repr__(self) -> str:
        return (f"FactorResult({self.name}, IC={self.train_ic:+.4f}, "
                f"score={self.score:.4f}, category={self.category})")


# ================================================================
# 方案一: 遗传编程 (GP) 因子挖掘
# ================================================================

class GPFactorMiner:
    """
    基于遗传编程的因子公式自动搜索。

    依赖 deap 库（pip install deap）。
    使用 sklearn 决策树划分的 Regime 数据，在每个叶子节点内独立运行 GP。

    Example:
        miner = GPFactorMiner(GPMinerConfig(population_size=50, n_generations=25))
        best = miner.mine(
            feature_dicts, labels, feature_names,
            use_pooled=False, seed=42,
        )
    """

    def __init__(self, config: Optional[GPMinerConfig] = None):
        self.config = config or GPMinerConfig()
        self.pset_ = None
        self.toolbox_ = None

    def _build_pset(self, feature_names: List[str]):
        """构建 GP 原语集合"""
        import deap.gp as gp
        self.pset_ = gp.PrimitiveSet("MAIN", len(feature_names))

        # 二元运算符
        self.pset_.addPrimitive(v_add, 2)
        self.pset_.addPrimitive(v_sub, 2)
        self.pset_.addPrimitive(v_mul, 2)
        self.pset_.addPrimitive(v_div, 2)
        self.pset_.addPrimitive(v_max, 2)
        self.pset_.addPrimitive(v_min, 2)

        # 一元运算符
        self.pset_.addPrimitive(v_rank, 1)
        self.pset_.addPrimitive(v_abs, 1)
        self.pset_.addPrimitive(v_log, 1)
        self.pset_.addPrimitive(v_neg, 1)
        self.pset_.addPrimitive(v_sgn, 1)

        # 重命名参数
        self.pset_.renameArguments(**{
            f"ARG{i}": name for i, name in enumerate(feature_names)
        })

        return self.pset_

    def _build_toolbox(
        self,
        feature_dicts: List[Dict[str, np.ndarray]],
        labels: List[np.ndarray],
        feature_names: List[str],
        use_pooled: bool = False,
    ):
        """构建 deap toolbox"""
        import deap.base as base
        import deap.creator as creator
        import deap.gp as gp
        import deap.tools as tools

        # 清理残留
        for name in ['FitnessMax', 'Individual']:
            if name in creator.__dict__:
                del creator.__dict__[name]

        creator.create("FitnessMax", base.Fitness, weights=(1.0,))
        creator.create("Individual", gp.PrimitiveTree, fitness=creator.FitnessMax)

        toolbox = base.Toolbox()
        toolbox.register("expr", gp.genHalfAndHalf, pset=self.pset_,
                         min_=self.config.init_min_depth,
                         max_=self.config.init_max_depth)
        toolbox.register("individual", tools.initIterate,
                         creator.Individual, toolbox.expr)
        toolbox.register("population", tools.initRepeat,
                         list, toolbox.individual)
        toolbox.register("compile", gp.compile, pset=self.pset_)

        def _evaluate(ind):
            """适应度函数：IC - 0.5 * IC_std（稳定IC优先）"""
            try:
                func = toolbox.compile(ind)
            except Exception:
                return (-999,)

            if use_pooled:
                return self._eval_pooled(func, feature_dicts, labels, feature_names)
            else:
                return self._eval_period(func, feature_dicts, labels, feature_names)

        toolbox.register("evaluate", _evaluate)
        toolbox.register("select", tools.selTournament,
                         tournsize=self.config.tournament_size)
        toolbox.register("mate", gp.cxOnePoint)
        toolbox.register("expr_mut", gp.genFull, min_=0, max_=2)
        toolbox.register("mutate", gp.mutUniform,
                         expr=toolbox.expr_mut, pset=self.pset_)

        # 树高度约束
        toolbox.decorate("mate", gp.staticLimit(
            key=operator.attrgetter('height'),
            max_value=self.config.max_tree_height))
        toolbox.decorate("mutate", gp.staticLimit(
            key=operator.attrgetter('height'),
            max_value=self.config.max_tree_height))

        self.toolbox_ = toolbox
        return toolbox

    @staticmethod
    def _eval_pooled(func, feature_dicts, labels, feature_names) -> Tuple[float]:
        """池化评估：合并所有截面算一次 IC"""
        all_pred, all_actual = [], []
        for feats, lab in zip(feature_dicts, labels):
            try:
                args = [safe_nan_to_num(feats[n]) for n in feature_names]
                all_pred.append(func(*args).flatten())
                all_actual.append(lab.flatten())
            except Exception:
                pass
        if not all_pred:
            return (-999,)
        pred = np.concatenate(all_pred)
        actual = np.concatenate(all_actual)
        mask = np.isfinite(pred) & np.isfinite(actual)
        if mask.sum() < 30:
            return (-999,)
        ic = np.corrcoef(pred[mask], actual[mask])[0, 1]
        if not np.isfinite(ic) or abs(ic) < 1e-10:
            return (-999,)
        if np.std(pred[mask]) < 1e-10:  # 常数输出 → 退化
            return (-999,)
        return (ic,)

    @staticmethod
    def _eval_period(func, feature_dicts, labels, feature_names) -> Tuple[float]:
        """逐截面评估：取 mean_IC - 0.5 * std_IC"""
        ics = []
        for feats, lab in zip(feature_dicts, labels):
            try:
                args = [safe_nan_to_num(feats[n]) for n in feature_names]
                pred = func(*args).flatten()
                actual = lab.flatten()
                mask = np.isfinite(pred) & np.isfinite(actual)
                if mask.sum() >= 5:
                    ic = np.corrcoef(pred[mask], actual[mask])[0, 1]
                    if np.isfinite(ic):
                        ics.append(ic)
            except Exception:
                pass
        if len(ics) < 5:
            return (-999,)
        std_ic = np.std(ics)
        if std_ic < 1e-8:  # 常数输出
            return (-999,)
        return (np.mean(ics) - 0.5 * std_ic,)

    def mine(
        self,
        feature_dicts: List[Dict[str, np.ndarray]],
        labels: List[np.ndarray],
        feature_names: List[str],
        use_pooled: bool = False,
        seed: int = 42,
        verbose: bool = True,
    ) -> Optional[FactorResult]:
        """
        运行 GP 搜索。

        Args:
            feature_dicts: 每期特征字典列表 [{fn: arr}, ...]
            labels: 每期目标值列表 [arr, ...]
            feature_names: 特征名列表
            use_pooled: 是否池化评估
            seed: 随机种子
            verbose: 打印进度

        Returns:
            FactorResult 或 None（搜索失败）
        """
        import deap.algorithms as algorithms
        import deap.tools as tools

        n_periods = len(feature_dicts)
        n_samples = sum(len(l) for l in labels)
        if n_periods < 5 or n_samples < 100:
            if verbose:
                print(f"  [GP] 数据不足 (periods={n_periods}, samples={n_samples})，跳过")
            return None

        # 构建
        self._build_pset(feature_names)
        toolbox = self._build_toolbox(
            feature_dicts, labels, feature_names, use_pooled)

        random.seed(seed)
        np.random.seed(seed)

        pop = toolbox.population(n=self.config.population_size)
        hof = tools.HallOfFame(1)

        stats = tools.Statistics(lambda ind: ind.fitness.values[0])
        stats.register("avg", np.mean)
        stats.register("max", np.max)

        pop, logbook = algorithms.eaSimple(
            pop, toolbox,
            cxpb=self.config.crossover_prob,
            mutpb=self.config.mutation_prob,
            ngen=self.config.n_generations,
            stats=stats,
            halloffame=hof,
            verbose=False,
        )

        if len(hof) == 0:
            if verbose:
                print(f"  [GP] Hall of Fame 为空")
            return None

        best_ind = hof[0]
        try:
            best_func = toolbox.compile(best_ind)
            best_str = str(best_ind)
        except Exception:
            if verbose:
                print(f"  [GP] 公式编译失败")
            return None

        # 计算评估指标
        if use_pooled:
            all_pred_p, all_actual_p = [], []
            for feats, lab in zip(feature_dicts, labels):
                try:
                    args = [safe_nan_to_num(feats[n]) for n in feature_names]
                    all_pred_p.append(best_func(*args).flatten())
                    all_actual_p.append(lab.flatten())
                except Exception:
                    pass
            if all_pred_p:
                pp = np.concatenate(all_pred_p)
                aa = np.concatenate(all_actual_p)
                m = np.isfinite(pp) & np.isfinite(aa)
                train_ic = np.corrcoef(pp[m], aa[m])[0, 1] if m.sum() >= 30 else -999
                ic_std = 0.0
            else:
                train_ic = -999
                ic_std = 0.0
        else:
            ics = []
            for feats, lab in zip(feature_dicts, labels):
                try:
                    args = [safe_nan_to_num(feats[n]) for n in feature_names]
                    pred = best_func(*args).flatten()
                    actual = lab.flatten()
                    m = np.isfinite(pred) & np.isfinite(actual)
                    if m.sum() >= 5:
                        ic = np.corrcoef(pred[m], actual[m])[0, 1]
                        if np.isfinite(ic):
                            ics.append(ic)
                except Exception:
                    pass
            train_ic = np.mean(ics) if ics else -999
            ic_std = np.std(ics) if ics else 0.0

        icir = train_ic / ic_std if ic_std > 1e-12 else 0.0

        if verbose:
            expr_short = best_str[:70] + ('...' if len(best_str) > 70 else '')
            print(f"  [GP] Best: {expr_short}")
            print(f"       IC={train_ic:+.4f}  ICIR={icir:+.3f}  "
                  f"periods={n_periods}  samples={n_samples}")

        return FactorResult(
            name="GP_Auto",
            expression=best_str,
            category="gp",
            train_ic=float(train_ic),
            ic_std=float(ic_std),
            icir=float(icir),
            score=float(train_ic),
        )


# ================================================================
# 方案二: 知识引导模板因子挖掘
# ================================================================

class TemplateMiner:
    """
    基于知识模板的因子评估引擎。

    将人类先验（反转、趋势、低波等）编码为预定义公式模板，
    在给定数据上评估每条模板的预测能力。

    Example:
        miner = TemplateMiner()
        results = miner.mine(features, target, train_mask)
    """

    def __init__(self):
        self.templates = self._build_templates()

    @staticmethod
    def _build_templates() -> List[Dict]:
        """
        构建因子模板库。

        每个模板包含:
          - name:     因子名称
          - expr:     计算公式 (Python 表达式, 可用特征名作为变量)
          - logic:    逻辑说明
          - category: rev(反转) / trend(趋势) / lowvol(低波) / universal(通用)
          - required: 依赖的特征名列表
        """
        templates = []

        # ========== Mean-Reversion (反转) ==========
        templates.extend([
            {"name": "rsi14_rev", "expr": "-(rsi_14 - 50) / 50",
             "logic": "RSI14超买回落超卖反弹", "category": "rev",
             "required": ["rsi_14"]},
            {"name": "rsi21_rev", "expr": "-(rsi_21 - 50) / 50",
             "logic": "RSI21更长周期极端值回归", "category": "rev",
             "required": ["rsi_21"]},
            {"name": "bb_rev", "expr": "-(bb_position - 0.5) * 2",
             "logic": "布林带极端位置回复", "category": "rev",
             "required": ["bb_position"]},
            {"name": "ma_rev", "expr": "-ma5_ma20",
             "logic": "短均偏离长均回复", "category": "rev",
             "required": ["ma5_ma20"]},
            {"name": "gap_rev", "expr": "-gap / (close + 1e-8)",
             "logic": "跳空缺口回补", "category": "rev",
             "required": ["gap", "close"]},
            {"name": "vol_spike_rev", "expr": "-rel_vol",
             "logic": "放量后缩量→价格反向", "category": "rev",
             "required": ["rel_vol"]},
            {"name": "max_ret_rev", "expr": "-max_ret_20",
             "logic": "大涨后获利了结", "category": "rev",
             "required": ["max_ret_20"]},
            {"name": "min_ret_rev", "expr": "-min_ret_20",
             "logic": "暴跌后超跌反弹", "category": "rev",
             "required": ["min_ret_20"]},
            {"name": "zscore_rev", "expr": "-(zscore_20 - 0)",
             "logic": "偏离20日均值回复", "category": "rev",
             "required": ["zscore_20"]},
            {"name": "skew_rev", "expr": "-skew_20d",
             "logic": "负偏度反转", "category": "rev",
             "required": ["skew_20d"]},
        ])

        # ========== Trend-Following (趋势) ==========
        templates.extend([
            {"name": "mom10", "expr": "ret_10d",
             "logic": "10日动量:强者恒强", "category": "trend",
             "required": ["ret_10d"]},
            {"name": "macdh_trend", "expr": "macdh",
             "logic": "MACD柱:多空动量方向", "category": "trend",
             "required": ["macdh"]},
            {"name": "ma_cross", "expr": "ma5_ma20",
             "logic": "短均上穿长均趋势信号", "category": "trend",
             "required": ["ma5_ma20"]},
            {"name": "breakout", "expr": "-dist_hh20",
             "logic": "距高点越近越可能突破", "category": "trend",
             "required": ["dist_hh20"]},
            {"name": "roc_adj", "expr": "roc_20 / (vol_20d + 1e-8)",
             "logic": "风险调整动量:夏普式动量", "category": "trend",
             "required": ["roc_20", "vol_20d"]},
            {"name": "vwap_trend", "expr": "vwap_div",
             "logic": "价格持续高于VWAP→资金流入", "category": "trend",
             "required": ["vwap_div"]},
            {"name": "ema_slope_trend", "expr": "ema_slope",
             "logic": "均线斜率:大趋势方向", "category": "trend",
             "required": ["ema_slope"]},
        ])

        # ========== Low-Vol Anomaly (低波异象) ==========
        templates.extend([
            {"name": "low_vol", "expr": "-vol_20d",
             "logic": "低波动异象(Bali & Cakici, 2008)", "category": "lowvol",
             "required": ["vol_20d"]},
            {"name": "range_compress", "expr": "range_compress",
             "logic": "振幅压缩→突破前兆", "category": "lowvol",
             "required": ["range_compress"]},
            {"name": "body_shrink", "expr": "-body_ratio",
             "logic": "实体缩小→变盘信号", "category": "lowvol",
             "required": ["body_ratio"]},
            {"name": "vol_dry_up", "expr": "vol_dry",
             "logic": "缩量整理→择向突破", "category": "lowvol",
             "required": ["vol_dry"]},
            {"name": "tr_narrow_sig", "expr": "tr_narrow",
             "logic": "波幅收敛→趋势重启", "category": "lowvol",
             "required": ["tr_narrow"]},
            {"name": "wick_signal", "expr": "-(wick_body_r - 1)",
             "logic": "长影线→多空分歧→反转", "category": "lowvol",
             "required": ["wick_body_r"]},
            {"name": "obv_z_signal", "expr": "obv_z",
             "logic": "OBV标准化:量价背离检测", "category": "lowvol",
             "required": ["obv_z"]},
        ])

        # ========== Cross-Regime Universal ==========
        templates.extend([
            {"name": "kurt_premium", "expr": "-kurt_20d",
             "logic": "高峰度风险溢价", "category": "universal",
             "required": ["kurt_20d"]},
            {"name": "ret_range_rev", "expr": "-ret_range_20",
             "logic": "高波动区间→均值回复", "category": "universal",
             "required": ["ret_range_20"]},
            {"name": "vol_contract_sig", "expr": "vol_contract",
             "logic": "波动收缩→方向选择", "category": "universal",
             "required": ["vol_contract"]},
        ])

        return templates

    def mine(
        self,
        features: Dict[str, np.ndarray],
        target: np.ndarray,
        train_mask: np.ndarray,
        test_mask: Optional[np.ndarray] = None,
        verbose: bool = True,
    ) -> List[FactorResult]:
        """
        评估所有模板因子。

        Args:
            features: 特征字典 {name: array[n]}
            target: 目标值 array[n]
            train_mask: 训练集掩码
            test_mask: 测试集掩码（可选）
            verbose: 打印进度

        Returns:
            FactorResult 列表，按 score 降序排列
        """
        results = []
        local_ns = features.copy()

        for tmpl in self.templates:
            try:
                # 检查所需特征是否齐全
                missing = [r for r in tmpl["required"] if r not in features]
                if missing:
                    continue

                # 安全计算因子值
                fv = eval(tmpl["expr"], {"__builtins__": {}}, local_ns)
                fv = safe_nan_to_num(np.asarray(fv, dtype=np.float64),
                                     posinf=1e6, neginf=-1e6)

                valid = train_mask & np.isfinite(target) & np.isfinite(fv)

                if valid.sum() < 30:
                    continue

                # 训练集 IC
                train_ic = spearman_correlation(fv[valid], target[valid])
                if not np.isfinite(train_ic):
                    continue

                # 测试集 IC（如果提供）
                test_ic = 0.0
                if test_mask is not None:
                    test_valid = test_mask & np.isfinite(target) & np.isfinite(fv)
                    if test_valid.sum() >= 30:
                        test_ic = spearman_correlation(
                            fv[test_valid], target[test_valid])
                        if not np.isfinite(test_ic):
                            test_ic = 0.0

                # 综合评分
                gap = abs(train_ic - test_ic) if (abs(train_ic) > 0.02 and abs(test_ic) > 0.02) else 0.0
                score = abs(test_ic) - 0.3 * gap - 0.1 * abs(train_ic) * (abs(train_ic) < 0.03)

                results.append(FactorResult(
                    name=tmpl["name"],
                    expression=tmpl["expr"],
                    category=tmpl["category"],
                    logic_description=tmpl["logic"],
                    train_ic=float(train_ic),
                    test_ic=float(test_ic),
                    score=float(score),
                    factor_values=fv.copy(),
                ))

            except Exception:
                continue

        # 按得分降序
        results.sort(key=lambda x: x.score, reverse=True)

        if verbose and results:
            print(f"\n  [Template] 评估了 {len(self.templates)} 条模板, "
                  f"有效 {len(results)} 个")
            print(f"\n  {'排名':<4} {'因子':<18} {'类型':<8} "
                  f"{'TrainIC':>8} {'TestIC':>8} {'Score':>8}   {'逻辑'}")
            print(f"  {'-'*70}")
            for i, r in enumerate(results[:10]):
                print(f"  {i+1:<4} {r.name:<18} {r.category:<8} "
                      f"{r.train_ic:>+8.4f} {r.test_ic:>+8.4f} "
                      f"{r.score:>8.4f}   {r.logic_description[:40]}")

        return results

    def mine_per_regime(
        self,
        features: Dict[str, np.ndarray],
        target: np.ndarray,
        regime_labels: np.ndarray,
        train_mask: np.ndarray,
        test_mask: np.ndarray,
        verbose: bool = True,
    ) -> Dict[int, List[FactorResult]]:
        """
        在每个 Regime 内独立评估模板因子。

        Returns:
            {regime_id: [FactorResult, ...]}
        """
        results_by_regime = {}
        for ri in np.unique(regime_labels):
            rm = regime_labels == ri
            r_train = rm & train_mask
            r_test = rm & test_mask

            if r_train.sum() < 15:
                continue

            if verbose:
                print(f"\n  ── Regime {int(ri)} (train={r_train.sum()}天, "
                      f"test={r_test.sum()}天) ──")

            regime_results = self.mine(
                features, target, r_train, r_test, verbose=verbose)
            results_by_regime[int(ri)] = regime_results

        return results_by_regime
