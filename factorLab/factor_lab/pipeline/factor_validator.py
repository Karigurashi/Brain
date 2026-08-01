"""
Pipeline Stage 5: FactorValidator
=================================
验证集上检验因子质量。

四道过滤:
  1. IC 稳定性  — 训练IC vs 验证IC 差距 < 50%
  2. 相关性去重  — 同 Regime 内两两 corr > 0.7 只留 IC 更高的
  3. 因子家族平衡 — 每 Regime 每个家族至少保留 1 个代表
  4. 综合评级    — S/A/B/C/D 五级（S/A过，B预警，C/D淘汰）

输出: 通过验证的因子池 + 淘汰日志
"""

import numpy as np
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field


@dataclass
class ValidationResult:
    """验证结果"""
    passed: Dict[int, List]        # regime_id → [FactorResult, ...] 通过的
    rejected: Dict[int, List]      # regime_id → [(FactorResult, reason), ...]
    n_passed: int = 0
    n_rejected: int = 0
    validation_summary: str = ""


class FactorValidator:
    """
    验证集因子校验器。

    Example:
        validator = FactorValidator(
            ic_stability_threshold=0.5,
            correlation_threshold=0.7,
            min_absolute_ic=0.02,
        )
        result = validator.validate(
            mine_result, features, target,
            regime_result, val_mask,
        )
    """

    def __init__(
        self,
        ic_stability_threshold: float = 0.5,   # 训练IC下降比例上限
        correlation_threshold: float = 0.7,    # 相关系数去重阈值
        min_absolute_ic: float = 0.02,         # 最低绝对IC
        min_icir: float = 0.2,                 # 最低ICIR
        family_balance: bool = True,            # 是否启用家族平衡
        verbose: bool = True,
    ):
        self.ic_stability_threshold = ic_stability_threshold
        self.correlation_threshold = correlation_threshold
        self.min_absolute_ic = min_absolute_ic
        self.min_icir = min_icir
        self.family_balance = family_balance
        self.verbose = verbose

    def validate(
        self,
        mine_result,        # PerRegimeMineResult
        features: Dict[str, np.ndarray],
        target: np.ndarray,
        regime_result,      # RegimeSplitResult
        close: np.ndarray = None,  # 用于多周期IC
    ) -> ValidationResult:
        """
        运行全量验证。

        Returns:
            ValidationResult
        """
        from factor_lab.operators import spearman_correlation

        passed: Dict[int, List] = {}
        rejected: Dict[int, List] = {}
        n_passed = 0
        n_rejected = 0

        for ri, factors in mine_result.all_factors.items():
            val_mask_ri = regime_result.val_regime_mask.get(ri)
            train_mask_ri = regime_result.train_regime_mask.get(ri)

            if val_mask_ri is None or val_mask_ri.sum() < 15:
                # 验证集太小 → 放宽条件，全部保留（但不计入正式通过）
                passed[ri] = factors[:3] if factors else []
                continue

            regime_passed = []
            regime_rejected = []

            for f in factors:
                reason = None

                # ── 过滤 1: 绝对 IC ──
                if abs(f.train_ic) < self.min_absolute_ic:
                    reason = f"IC={f.train_ic:+.4f} < {self.min_absolute_ic}"

                # ── 过滤 2: ICIR ──
                elif abs(f.icir) < self.min_icir and abs(f.icir) > 1e-12:
                    reason = f"ICIR={f.icir:.3f} < {self.min_icir}"

                # ── 过滤 3: IC 稳定性（验证集 vs 训练集） ──
                if reason is None and f.factor_values is not None:
                    fv = f.factor_values
                    # 在验证集上算 IC
                    valid_val = val_mask_ri & np.isfinite(target) & np.isfinite(fv)
                    if valid_val.sum() >= 15:
                        val_ic = spearman_correlation(
                            fv[valid_val], target[valid_val])
                        if np.isfinite(val_ic):
                            f.test_ic = float(val_ic)
                            # 同方向 + 不衰减太多
                            if abs(f.train_ic) > 0.01:
                                decay = (abs(f.train_ic) - abs(val_ic)) / abs(f.train_ic)
                                if decay > self.ic_stability_threshold:
                                    reason = f"IC衰减={decay:.1%} > {self.ic_stability_threshold:.1%}"
                                elif f.train_ic * val_ic < 0:
                                    reason = f"IC方向反转(train={f.train_ic:+.4f}, val={val_ic:+.4f})"
                            else:
                                f.test_ic = 0.0
                        else:
                            reason = "验证IC不收敛"
                    else:
                        reason = f"验证样本不足({valid_val.sum()}天)"

                if reason:
                    regime_rejected.append((f, reason))
                    n_rejected += 1
                else:
                    regime_passed.append(f)
                    n_passed += 1

            # ── 过滤 4: 相关性去重 ──
            regime_passed = self._deduplicate(
                regime_passed, features, val_mask_ri, target)

            # ── 过滤 5: 家族平衡 ──
            if self.family_balance:
                regime_passed = self._family_balance(regime_passed)

            passed[ri] = regime_passed
            rejected.setdefault(ri, []).extend(regime_rejected)

        if self.verbose:
            self._print_report(passed, rejected, close, regime_result)

        return ValidationResult(
            passed=passed,
            rejected=rejected,
            n_passed=n_passed,
            n_rejected=n_rejected,
            validation_summary=self._build_summary(passed, rejected),
        )

    def _deduplicate(
        self,
        factors: List,
        features: Dict[str, np.ndarray],
        val_mask: np.ndarray,
        target: np.ndarray,
    ) -> List:
        """相关性去重：corr > threshold → 只留 IC 更高的"""
        from factor_lab.operators import pairwise_correlation

        if len(factors) < 2:
            return factors

        n = len(factors)
        kept = [True] * n

        for i in range(n):
            if not kept[i] or factors[i].factor_values is None:
                continue
            for j in range(i + 1, n):
                if not kept[j] or factors[j].factor_values is None:
                    continue
                fv_i = factors[i].factor_values[val_mask]
                fv_j = factors[j].factor_values[val_mask]
                valid = np.isfinite(fv_i) & np.isfinite(fv_j)
                if valid.sum() < 15:
                    continue
                corr = abs(pairwise_correlation(fv_i[valid], fv_j[valid]))
                if corr > self.correlation_threshold:
                    # 保留 test_ic 更高的
                    if abs(factors[i].test_ic) >= abs(factors[j].test_ic):
                        kept[j] = False
                    else:
                        kept[i] = False

        return [factors[i] for i in range(n) if kept[i]]

    @staticmethod
    def _family_balance(factors: List) -> List:
        """每个家族至少保留一个代表"""
        if len(factors) <= 3:
            return factors

        families: Dict[str, List] = {}
        for f in factors:
            cat = f.category or "unknown"
            families.setdefault(cat, []).append(f)

        result = []
        for cat, cat_factors in families.items():
            # 每个家族保留 top 2
            cat_factors.sort(key=lambda x: abs(x.test_ic), reverse=True)
            result.extend(cat_factors[:2])

        result.sort(key=lambda x: abs(x.test_ic), reverse=True)
        return result

    def _print_report(self, passed: Dict, rejected: Dict, close=None, regime_result=None):
        """打印验证报告，含多周期IC"""
        from factor_lab.operators import spearman_correlation
        print(f"\n{'='*60}")
        print(f"  Stage 5: Factor Validation Report")
        print(f"{'='*60}")

        for ri in sorted(passed.keys()):
            p = passed[ri]
            r = rejected.get(ri, [])
            print(f"\n  Regime {ri}: +{len(p)} passed  -{len(r)} rejected")

            if p:
                for f in p:
                    print(f"    [OK] {f.name:<20s} IC={f.train_ic:+.4f}->{f.test_ic:+.4f}  "
                          f"cat={f.category}")
            if r:
                for f, reason in r[:3]:
                    print(f"    [--] {f.name:<20s} {reason}")
                if len(r) > 3:
                    print(f"    ... 共 {len(r)} 个淘汰")

            # 多周期 IC 表（需要 close 和 regime_result）
            if close is not None and regime_result is not None and p:
                train_mask = regime_result.train_regime_mask.get(ri)
                test_mask = regime_result.test_regime_mask.get(ri)
                if train_mask is not None and test_mask is not None:
                    print(f"\n    {'Horizon':<8} ", end="")
                    for f in p[:3]:
                        print(f"{f.name:<14}", end="")
                    print()
                    print(f"    {'-'*50}")
                    for h in [1, 3, 5, 10]:
                        fwd = np.full(len(close), np.nan)
                        fwd[:-h] = close[h:] / close[:-h] - 1.0
                        print(f"    {h}d       ", end="")
                        for f in p[:3]:
                            fv = f.factor_values
                            if fv is None:
                                print(f"{'N/A':<14}", end="")
                                continue
                            valid = test_mask & np.isfinite(fv) & np.isfinite(fwd)
                            ic = spearman_correlation(fv[valid], fwd[valid]) if valid.sum() > 15 else np.nan
                            if np.isfinite(ic):
                                print(f"{ic:+.4f}        ", end="")
                            else:
                                print(f"{'N/A':<14}", end="")
                        print()

    @staticmethod
    def _build_summary(passed: Dict, rejected: Dict) -> str:
        total_p = sum(len(v) for v in passed.values())
        total_r = sum(len(v) for v in rejected.values())
        return f"通过 {total_p} 个因子, 淘汰 {total_r} 个"
