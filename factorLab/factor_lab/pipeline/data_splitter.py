"""
Pipeline Stage 2: DataSplitter
==============================
两种模式:
  1. SimpleSplitter  - 单次 Train/Val/Test 拆分（旧模式，向后兼容）
  2. PurgedWalkForward - Purged Walk-Forward 多窗口拆分（推荐）

核心原则:
  - 严格时序拆分（禁止未来信息泄露）
  - Purge: 剔除特征窗口重叠，防止信息泄露
  - 多窗口：不是赌一个 Test 区间，而是看因子在多个样本外时期的稳定性

用法:
    splitter = DataSplitter(n_splits=5, train_ratio=0.6, purge_days=20)
    result = splitter.split(n_samples, dates)
"""

import numpy as np
from typing import List, Optional, Dict, Tuple
from dataclasses import dataclass, field


# ================================================================
# SplitResult
# ================================================================

@dataclass
class SplitResult:
    """单次数据拆分结果"""
    train_mask: np.ndarray    # bool [n]
    val_mask: np.ndarray      # bool [n]
    test_mask: np.ndarray     # bool [n]
    train_start: str = ""
    train_end: str = ""
    val_start: str = ""
    val_end: str = ""
    test_start: str = ""
    test_end: str = ""
    n_total: int = 0
    n_train: int = 0
    n_val: int = 0
    n_test: int = 0
    # Walk-Forward 元信息
    window_index: int = -1           # 第几个窗口（-1 表单一拆分）
    purge_end_idx: int = -1          # purge 结束位置
    embargo_end_idx: int = -1        # embargo 结束位置


# ================================================================
# WalkForwardSplitResult: 多窗口聚合结果
# ================================================================

@dataclass
class WalkForwardSplitResult:
    """Purged Walk-Forward 多窗口拆分结果"""
    splits: List[SplitResult] = field(default_factory=list)
    n_splits: int = 0
    purge_days: int = 0
    embargo_days: int = 0
    n_total: int = 0
    total_train_min: int = 0
    total_train_max: int = 0
    total_test_per_window: int = 0

    def summary(self) -> str:
        lines = [
            f"\n{'='*70}",
            f"  Purged Walk-Forward 拆分报告",
            f"{'='*70}",
            f"  总样本: {self.n_total} 个交易日",
            f"  窗口数: {self.n_splits}",
            f"  Purge: {self.purge_days}d  |  Embargo: {self.embargo_days}d",
            f"  Test/窗口: {self.total_test_per_window}d",
            f"",
            f"  {'Window':<8s} {'Train':>20s} {'Purge→':>8s} {'Test':>22s} {'Train天':>8s} {'Test天':>7s}",
            f"  {'-'*80}",
        ]
        for sp in self.splits:
            train_range = f"{sp.train_start}→{sp.train_end}"
            test_range = f"{sp.test_start}→{sp.test_end}"
            purge_info = f"{sp.purge_end_idx - sp.n_train}d" if sp.purge_end_idx >= 0 else "-"
            lines.append(
                f"  W{sp.window_index:<7d} {train_range:>20s}  {purge_info:>6s}  {test_range:>22s} "
                f"{sp.n_train:>8d} {sp.n_test:>7d}"
            )
        lines.append(f"\n  [核心价值] 因子需在 {self.n_splits} 个独立样本外窗口上保持一致表现")
        return "\n".join(lines)


# ================================================================
# SimpleSplitter: 旧版单次拆分（向后兼容）
# ================================================================

class DataSplitter:
    """
    时序数据拆分器（旧版单次模式，保持向后兼容）。

    规则:
      - train: 前 train_ratio 的数据（默认 60%）
      - val:   中间 val_ratio 的数据（默认 20%）
      - test:  最后剩余数据（默认 20%）
    """

    def __init__(
        self,
        train_ratio: float = 0.60,
        val_ratio: float = 0.20,
        min_train_days: int = 252,
        min_val_days: int = 60,
        min_test_days: int = 60,
    ):
        assert train_ratio + val_ratio < 1.0, "train + val must be < 1.0"
        self.train_ratio = train_ratio
        self.val_ratio = val_ratio
        self.min_train_days = min_train_days
        self.min_val_days = min_val_days
        self.min_test_days = min_test_days

    def split(
        self,
        n: int,
        dates: Optional[List[str]] = None,
    ) -> SplitResult:
        train_cut = int(n * self.train_ratio)
        val_cut = int(n * (self.train_ratio + self.val_ratio))

        if train_cut < self.min_train_days:
            train_cut = min(self.min_train_days, n - self.min_val_days - self.min_test_days)
        if val_cut - train_cut < self.min_val_days:
            val_cut = min(train_cut + self.min_val_days, n - self.min_test_days)
        if n - val_cut < self.min_test_days:
            val_cut = max(train_cut + 1, n - self.min_test_days)

        train_mask = np.zeros(n, dtype=bool)
        val_mask = np.zeros(n, dtype=bool)
        test_mask = np.zeros(n, dtype=bool)

        train_mask[:train_cut] = True
        val_mask[train_cut:val_cut] = True
        test_mask[val_cut:] = True

        result = SplitResult(
            train_mask=train_mask, val_mask=val_mask, test_mask=test_mask,
            n_total=n, n_train=train_cut, n_val=val_cut - train_cut, n_test=n - val_cut,
        )
        if dates:
            result.train_start = dates[0]
            result.train_end = dates[train_cut - 1]
            result.val_start = dates[train_cut]
            result.val_end = dates[val_cut - 1]
            result.test_start = dates[val_cut]
            result.test_end = dates[-1]

        return result

    def split_at_dates(
        self, dates: List[str], train_end_date: str, val_end_date: str,
    ) -> SplitResult:
        n = len(dates)
        train_mask = np.zeros(n, dtype=bool)
        val_mask = np.zeros(n, dtype=bool)
        test_mask = np.zeros(n, dtype=bool)
        for i, d in enumerate(dates):
            if d <= train_end_date:
                train_mask[i] = True
            elif d <= val_end_date:
                val_mask[i] = True
            else:
                test_mask[i] = True
        train_cut = int(train_mask.sum())
        return SplitResult(
            train_mask=train_mask, val_mask=val_mask, test_mask=test_mask,
            n_total=n, n_train=train_cut, n_val=int(val_mask.sum()),
            n_test=int(test_mask.sum()),
            train_start=dates[0], train_end=dates[train_cut - 1],
            val_start=dates[train_cut], val_end=dates[train_cut + int(val_mask.sum()) - 1],
            test_start=dates[train_cut + int(val_mask.sum())], test_end=dates[-1],
        )

    def print_split(self, result: SplitResult):
        print(f"\n{'='*60}")
        print(f"  数据拆分报告")
        print(f"{'='*60}")
        print(f"  总样本: {result.n_total} 个交易日")
        for label, n, s, e in [
            ("Train", result.n_train, result.train_start, result.train_end),
            ("Val",   result.n_val,   result.val_start,   result.val_end),
            ("Test",  result.n_test,  result.test_start,  result.test_end),
        ]:
            ratio = n / result.n_total * 100
            print(f"  {label:<6s}: {n:>5d} ({ratio:>4.1f}%)  [{s} → {e}]")
        print(f"  {'-'*60}")
        print(f"  [WARNING] Test set must not be inspected during strategy development")


# ================================================================
# PurgedWalkForwardSplitter: 新增！推荐使用
# ================================================================

class PurgedWalkForwardSplitter:
    """
    Purged Walk-Forward 多窗口拆分器。

    参考: López de Prado, "Advances in Financial Machine Learning" (2018), Ch.7

    核心机制:
      1. Expanding Window：训练集从起始日逐步扩展
      2. Purge：剔除 Train 尾部与 Test 头部之间的特征窗口重叠区间
      3. Embargo：额外禁入区，防止慢信号泄露（训练标签用到 t+N 回报、
         而 Test 中 t+1 日可能仍受 Train 最后一日的标签影响）

    参数:
      n_splits:    窗口数量（默认 5，最少 3）
      train_ratio: 每个窗口训练占比（默认 0.60）
      purge_days:  Purge 天数，至少设为特征最大回溯窗口（默认 20）
      embargo_days:Embargo 天数（默认 0，如有 N 日预测目标建议 >= N）
      min_train_days: 最小训练天数（默认 252，一年）
      min_test_days:  最小测试天数（默认 40）

    使用:
        splitter = PurgedWalkForwardSplitter(
            n_splits=5, train_ratio=0.6, purge_days=20, embargo_days=3
        )
        wf = splitter.split(n=1000, dates=date_list)
        for sp in wf.splits:
            # sp.train_mask, sp.test_mask 在当前窗口使用
            # sp.val_mask 由 train_mask 尾部切出（可选）
            ...
    """

    def __init__(
        self,
        n_splits: int = 5,
        train_ratio: float = 0.60,
        purge_days: int = 20,
        embargo_days: int = 0,
        min_train_days: int = 252,
        min_test_days: int = 40,
        val_from_train_ratio: float = 0.20,   # 从 train 尾部切 val 的比例
    ):
        assert n_splits >= 2, "n_splits must be >= 2"
        assert 0.4 < train_ratio < 0.85, "train_ratio should be 0.4~0.85"
        assert purge_days >= 0, "purge_days must be >= 0"
        assert embargo_days >= 0, "embargo_days must be >= 0"

        self.n_splits = n_splits
        self.train_ratio = train_ratio
        self.purge_days = purge_days
        self.embargo_days = embargo_days
        self.min_train_days = min_train_days
        self.min_test_days = min_test_days
        self.val_from_train_ratio = val_from_train_ratio

    # ── 主方法 ──

    def split(
        self,
        n: int,
        dates: Optional[List[str]] = None,
    ) -> WalkForwardSplitResult:
        """
        执行 Purged Walk-Forward 拆分。

        Args:
            n:     总交易日数
            dates: 日期列表（可选）

        Returns:
            WalkForwardSplitResult，包含 n_splits 个 SplitResult
        """
        # ── 计算窗口边界 ──
        total_test_days = int(n * (1.0 - self.train_ratio))
        test_per_split = max(self.min_test_days, total_test_days // self.n_splits)

        # 调整: 如果 test 总量装不下 n_splits 个窗口，缩减 splits
        actual_splits = min(self.n_splits, total_test_days // self.min_test_days)
        if actual_splits < 2:
            actual_splits = 2
            test_per_split = max(self.min_test_days, total_test_days // actual_splits)

        if actual_splits < self.n_splits:
            print(f"  [Splitter] 数据量不足，窗口数 {self.n_splits} → {actual_splits}")

        # ── 生成每个窗口 ──
        splits = []
        test_start_indices = []

        for i in range(actual_splits):
            # Test 区间: 从尾部向前分配
            # split i 的 test 覆盖: [test_start_i, test_end_i)
            remaining_splits = actual_splits - i
            test_end = n - (remaining_splits - 1) * test_per_split
            test_start = test_end - test_per_split

            # Purge + Embargo
            purge_start = test_start - self.purge_days
            embargo_start = purge_start - self.embargo_days

            # Train 区间: [0, embargo_start)  （expanding window）
            train_end = max(self.min_train_days, embargo_start)

            if train_end < self.min_train_days:
                train_end = min(self.min_train_days, test_start - 1)

            # ── 构建 mask ──
            train_mask = np.zeros(n, dtype=bool)
            val_mask = np.zeros(n, dtype=bool)
            test_mask = np.zeros(n, dtype=bool)

            train_mask[:train_end] = True
            test_mask[test_start:test_end] = True

            # Val: 从 train 尾部切出一小段（用于因子筛选/扫参）
            val_size = max(20, int(train_end * self.val_from_train_ratio))
            val_start = train_end - val_size
            if val_start > 0:
                val_mask[val_start:train_end] = True
                train_mask[val_start:train_end] = False
                actual_train_end = val_start
            else:
                actual_train_end = train_end

            sp = SplitResult(
                train_mask=train_mask,
                val_mask=val_mask,
                test_mask=test_mask,
                n_total=n,
                n_train=int(train_mask.sum()),
                n_val=int(val_mask.sum()),
                n_test=int(test_mask.sum()),
                window_index=i,
                purge_end_idx=purge_start,
                embargo_end_idx=embargo_start,
            )

            if dates:
                sp.train_start = dates[0]
                sp.train_end = dates[actual_train_end - 1] if actual_train_end > 0 else ""
                if val_mask.sum() > 0:
                    sp.val_start = dates[val_start]
                    sp.val_end = dates[train_end - 1]
                sp.test_start = dates[test_start]
                sp.test_end = dates[test_end - 1]

            splits.append(sp)
            test_start_indices.append(test_start)

        wf = WalkForwardSplitResult(
            splits=splits,
            n_splits=actual_splits,
            purge_days=self.purge_days,
            embargo_days=self.embargo_days,
            n_total=n,
            total_train_min=min(s.n_train for s in splits),
            total_train_max=max(s.n_train for s in splits),
            total_test_per_window=test_per_split,
        )

        return wf

    # ── 便捷方法: 生成单次等效拆分（兼容旧接口）──

    def to_single_split(
        self,
        wf: WalkForwardSplitResult,
        include_val: bool = True,
    ) -> SplitResult:
        """
        从 Walk-Forward 结果生成单一等效拆分（向后兼容）。

        取第一个窗口的 train，最后一个窗口的 test，
        中间部分作为 val（或 purged）。
        """
        if not wf.splits:
            raise ValueError("No splits available")

        n = wf.n_total
        first = wf.splits[0]
        last = wf.splits[-1]

        train_end_idx = int(first.train_mask.sum() + first.val_mask.sum())
        test_start_idx = int(np.argmax(last.test_mask))

        train_mask = np.zeros(n, dtype=bool)
        val_mask = np.zeros(n, dtype=bool)
        test_mask = np.zeros(n, dtype=bool)

        train_mask[:train_end_idx] = True
        test_mask[test_start_idx:] = True

        if include_val:
            val_start = train_end_idx
            val_end = test_start_idx
            if val_end > val_start:
                val_mask[val_start:val_end] = True

        return SplitResult(
            train_mask=train_mask, val_mask=val_mask, test_mask=test_mask,
            n_total=n,
            n_train=int(train_mask.sum()),
            n_val=int(val_mask.sum()),
            n_test=int(test_mask.sum()),
        )

    # ── 便捷: 获取所有 test mask 的 OR（纯样本外覆盖范围）──

    @staticmethod
    def get_combined_test_mask(wf: WalkForwardSplitResult) -> np.ndarray:
        """返回所有窗口 test 的并集（纯样本外覆盖范围）"""
        combined = np.zeros(wf.n_total, dtype=bool)
        for sp in wf.splits:
            combined |= sp.test_mask
        return combined

    # ── 打印 ──

    def print_summary(self, wf: WalkForwardSplitResult):
        print(wf.summary())


# ================================================================
# 工厂函数: 根据模式创建拆分器
# ================================================================

def create_splitter(
    mode: str = "walk_forward",
    n_splits: int = 5,
    train_ratio: float = 0.60,
    val_ratio: float = 0.20,
    purge_days: int = 20,
    embargo_days: int = 0,
    **kwargs,
) -> Tuple[DataSplitter, PurgedWalkForwardSplitter]:
    """
    创建拆分器。

    Args:
        mode: "simple" | "walk_forward"
    Returns:
        (simple_splitter, walk_forward_splitter)
    """
    simple = DataSplitter(
        train_ratio=train_ratio,
        val_ratio=val_ratio,
        **{k: v for k, v in kwargs.items() if k in ['min_train_days', 'min_val_days', 'min_test_days']},
    )
    wf = PurgedWalkForwardSplitter(
        n_splits=n_splits,
        train_ratio=train_ratio,
        purge_days=purge_days,
        embargo_days=embargo_days,
        **{k: v for k, v in kwargs.items() if k in ['min_train_days', 'min_test_days']},
    )
    return simple, wf
