"""
Pipeline Stage 4: PerRegimeFactorMiner
======================================
在每个 Regime 内独立运行因子挖掘引擎。

双引擎并行:
  1. GPFactorMiner   — 遗传编程自动搜索（每个 Regime 独立运行）
  2. TemplateMiner    — 知识模板评估（每个 Regime 独立评估）

输出: 每个 Regime → Top N 因子

依赖: factor_lab.factor_miner
"""

import numpy as np
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field


@dataclass
class PerRegimeMineResult:
    """分 Regime 因子挖掘结果"""
    gp_factors: Dict[int, List]      # regime_id → [FactorResult, ...]
    template_factors: Dict[int, List]
    all_factors: Dict[int, List]     # 合并后的因子
    n_total_factors: int = 0
    n_regimes_processed: int = 0


class PerRegimeFactorMiner:
    """
    分 Regime 因子挖掘器。

    对每个 Regime:
      1. 提取该 Regime 训练期的特征子集
      2. 运行 GP 搜索（可选）
      3. 运行模板评估（可选）
      4. 合并 + 排序

    Example:
        miner = PerRegimeFactorMiner(
            gp_population_size=50, gp_generations=20,
            run_gp=True, run_template=True,
        )
        result = miner.mine(
            features, target, regime_result, split_result,
        )
    """

    def __init__(
        self,
        # GP 参数
        run_gp: bool = True,
        gp_population_size: int = 50,
        gp_generations: int = 20,
        gp_top_n_per_regime: int = 5,
        # Template 参数
        run_template: bool = True,
        template_top_n_per_regime: int = 5,
        # 通用
        random_seed: int = 42,
        verbose: bool = True,
    ):
        self.run_gp = run_gp
        self.gp_population_size = gp_population_size
        self.gp_generations = gp_generations
        self.gp_top_n_per_regime = gp_top_n_per_regime

        self.run_template = run_template
        self.template_top_n_per_regime = template_top_n_per_regime

        self.random_seed = random_seed
        self.verbose = verbose

    def mine(
        self,
        features: Dict[str, np.ndarray],
        target: np.ndarray,
        regime_result,   # RegimeSplitResult
        split_result,     # SplitResult
    ) -> PerRegimeMineResult:
        """
        分 Regime 挖掘。

        Args:
            features: 特征字典 {name: array[n]}
            target: 目标收益 [n]
            regime_result: RegimeSplitResult（含 regime_labels + per-regime masks）
            split_result: SplitResult（含 train_mask）

        Returns:
            PerRegimeMineResult
        """
        from factor_lab.factor_miner import GPFactorMiner, TemplateMiner, FactorResult
        from factor_lab.config import GPMinerConfig

        gp_factors: Dict[int, List] = {}
        template_factors: Dict[int, List] = {}
        all_factors: Dict[int, List] = {}
        n_total = 0
        n_processed = 0

        # 初始化引擎
        gp_miner = None
        if self.run_gp:
            gp_cfg = GPMinerConfig(
                population_size=self.gp_population_size,
                n_generations=self.gp_generations,
            )
            gp_miner = GPFactorMiner(gp_cfg)

        template_miner = None
        if self.run_template:
            template_miner = TemplateMiner()

        for ri in range(regime_result.n_regimes):
            train_mask_ri = regime_result.train_regime_mask.get(ri)
            if train_mask_ri is None or train_mask_ri.sum() < 30:
                if self.verbose:
                    print(f"  [Regime {ri}] 训练样本不足，跳过")
                continue

            val_mask_ri = regime_result.val_regime_mask.get(ri)

            if self.verbose:
                print(f"\n{'─'*50}")
                print(f"  Regime {ri}: 训练 {train_mask_ri.sum()} 天"
                      + (f"  验证 {val_mask_ri.sum()} 天" if val_mask_ri is not None else ""))

            regime_factors = []

            # ── GP 挖掘 ──
            if gp_miner is not None:
                try:
                    # 准备 GP 输入：需要 feature_dicts 和 labels 列表
                    feat_dicts_gp = []
                    labels_gp = []
                    # 将训练数据按"天"拆成截面（单票场景下每行是一个截面）
                    indices = np.where(train_mask_ri)[0]
                    for idx in indices:
                        day_feat = {k: np.array([v[idx]]) for k, v in features.items()}
                        day_label = np.array([target[idx]]) if np.isfinite(target[idx]) else np.array([0.0])
                        feat_dicts_gp.append(day_feat)
                        labels_gp.append(day_label)

                    gp_result = gp_miner.mine(
                        feat_dicts_gp, labels_gp,
                        feature_names=list(features.keys()),
                        use_pooled=True,  # 单票用池化
                        seed=self.random_seed + ri,
                        verbose=self.verbose,
                    )
                    if gp_result is not None:
                        gp_result.regime_id = ri
                        regime_factors.append(gp_result)
                        gp_factors.setdefault(ri, []).append(gp_result)
                except Exception as e:
                    if self.verbose:
                        print(f"  [GP Regime {ri}] 异常: {e}")

            # ── Template 挖掘 ──
            if template_miner is not None:
                try:
                    tmpl_results = template_miner.mine(
                        features, target,
                        train_mask=train_mask_ri,
                        test_mask=val_mask_ri,
                        verbose=False,  # 减少输出噪音
                    )
                    for tr in tmpl_results[:self.template_top_n_per_regime]:
                        tr.regime_id = ri
                        regime_factors.append(tr)
                    template_factors[ri] = tmpl_results[:self.template_top_n_per_regime]
                except Exception as e:
                    if self.verbose:
                        print(f"  [Template Regime {ri}] 异常: {e}")

            # 合并排序
            regime_factors.sort(key=lambda x: x.score, reverse=True)
            all_factors[ri] = regime_factors
            n_total += len(regime_factors)
            n_processed += 1

            if self.verbose and regime_factors:
                top3 = regime_factors[:3]
                print(f"  Top3: " + " | ".join(
                    f"{f.name}(IC={f.train_ic:+.3f},score={f.score:.3f})"
                    for f in top3))

        if self.verbose:
            print(f"\n{'='*50}")
            print(f"  因子挖掘完成: {n_processed}/{regime_result.n_regimes} 个 Regime, "
                  f"共 {n_total} 个因子")

        return PerRegimeMineResult(
            gp_factors=gp_factors,
            template_factors=template_factors,
            all_factors=all_factors,
            n_total_factors=n_total,
            n_regimes_processed=n_processed,
        )
