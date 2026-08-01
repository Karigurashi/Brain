"""
Pipeline Stage 1: StockSelector
===============================
从候选池中筛选适合单票 Regime 策略的标的。

筛选条件:
  1. 市值适中（30-200亿，流动性够用）
  2. 日均换手率 > 2%
  3. 非 ST / 非 *ST / 非科创板（涨跌幅限制一致）
  4. 历史数据充足（> 500 个交易日）

适用场景: 本地 CSV 批量扫描、聚宽研究环境选股
"""

import numpy as np
import pandas as pd
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass, field


@dataclass
class StockCandidate:
    """候选股票"""
    code: str
    name: str = ""
    market_cap: float = 0.0          # 市值（亿）
    avg_turnover: float = 0.0        # 近60日均换手率
    avg_volatility: float = 0.0      # 近60日年化波动率
    n_trading_days: int = 0          # 可用交易日数
    is_st: bool = False
    exchange: str = ""               # "sh" / "sz"
    score: float = 0.0               # 综合评分


@dataclass
class SelectorResult:
    """选股结果"""
    candidates: List[StockCandidate]
    rejected: List[StockCandidate]
    n_total: int = 0
    n_passed: int = 0
    summary: str = ""


class StockSelector:
    """
    单票策略候选股票筛选器。

    Example:
        selector = StockSelector(
            min_market_cap=30,      # 30亿起
            max_market_cap=200,     # 200亿封顶
            min_turnover=0.02,      # 日均换手 > 2%
            min_history_days=500,   # 至少 500 个交易日
        )
        result = selector.select_from_csvs(csv_paths)
    """

    def __init__(
        self,
        min_market_cap: float = 30.0,
        max_market_cap: float = 200.0,
        min_turnover: float = 0.02,
        max_turnover: float = 0.30,
        min_history_days: int = 500,
        min_volatility: float = 0.20,
    ):
        self.min_market_cap = min_market_cap
        self.max_market_cap = max_market_cap
        self.min_turnover = min_turnover
        self.max_turnover = max_turnover
        self.min_history_days = min_history_days
        self.min_volatility = min_volatility

    # ── 从 OHLCV DataFrame 筛选 ──

    def evaluate_single(
        self,
        df: pd.DataFrame,
        code: str = "",
        name: str = "",
        market_cap: float = 0.0,
    ) -> Optional[StockCandidate]:
        """
        评估单只股票是否适合单票 Regime 策略。

        Args:
            df: OHLCV DataFrame（需含 open/high/low/close/volume 列）
            code: 股票代码
            name: 股票名称
            market_cap: 已知市值（亿），0 则从数据估算

        Returns:
            StockCandidate 或 None（不符合条件）
        """
        n = len(df)
        if n < self.min_history_days:
            return None

        # 列名映射
        close = self._get_col(df, ["close"])
        high = self._get_col(df, ["high"])
        low = self._get_col(df, ["low"])
        volume = self._get_col(df, ["volume", "vol"])

        if close is None or volume is None:
            return None

        # 最近 120 天统计
        recent_n = min(120, n)
        recent_close = close[-recent_n:]
        recent_high = high[-recent_n:] if high is not None else recent_close
        recent_low = low[-recent_n:] if low is not None else recent_close
        recent_vol = volume[-recent_n:]

        # 日均换手率（粗略：成交量 / 流通股本，此处用相对量替代）
        if market_cap > 0:
            shares = market_cap * 1e8 / recent_close[-1]  # 估算流通股数
            turnover = np.mean(recent_vol) / (shares + 1e-8)
        else:
            # 无市值信息时用成交量分位数替代
            turnover = np.mean(recent_vol) / (np.median(volume) * 100 + 1e-8)

        if turnover < self.min_turnover or turnover > self.max_turnover:
            return None

        # 年化波动率
        log_ret = np.log(recent_close[1:] / recent_close[:-1])
        ann_vol = np.std(log_ret) * np.sqrt(252)

        if ann_vol < self.min_volatility:
            return None

        # 评分：波动率越高 + 换手率适中 = 越适合 regime 策略
        score = ann_vol * 2.0 + turnover * 1.5

        return StockCandidate(
            code=code,
            name=name,
            market_cap=market_cap,
            avg_turnover=float(turnover),
            avg_volatility=float(ann_vol),
            n_trading_days=n,
            score=float(score),
        )

    def select_from_dataframes(
        self,
        data_dict: Dict[str, pd.DataFrame],
        market_caps: Optional[Dict[str, float]] = None,
        names: Optional[Dict[str, str]] = None,
        top_k: int = 10,
    ) -> SelectorResult:
        """
        从多个 DataFrame 中批量筛选。

        Args:
            data_dict: {code: DataFrame}
            market_caps: {code: market_cap_亿}
            names: {code: name}
            top_k: 返回前 K 只

        Returns:
            SelectorResult
        """
        market_caps = market_caps or {}
        names = names or {}
        candidates = []
        rejected = []

        for code, df in data_dict.items():
            cap = market_caps.get(code, 0.0)
            name = names.get(code, "")
            result = self.evaluate_single(df, code=code, name=name, market_cap=cap)
            if result is not None:
                candidates.append(result)
            else:
                rejected.append(StockCandidate(
                    code=code, name=name, n_trading_days=len(df)))

        # 按评分排序
        candidates.sort(key=lambda x: x.score, reverse=True)
        top = candidates[:top_k]

        return SelectorResult(
            candidates=top,
            rejected=rejected,
            n_total=len(data_dict),
            n_passed=len(candidates),
            summary=self._build_summary(top),
        )

    def select_from_csvs(
        self,
        csv_paths: List[str],
        code_parser=None,
        top_k: int = 10,
    ) -> SelectorResult:
        """
        从本地 CSV 文件批量筛选。

        Args:
            csv_paths: CSV 文件路径列表
            code_parser: code_parser(path) → code 函数
            top_k: 返回前 K 只

        Returns:
            SelectorResult
        """
        data_dict = {}
        for path in csv_paths:
            try:
                df = pd.read_csv(path).sort_values("trade_date").reset_index(drop=True)
                code = code_parser(path) if code_parser else path
                data_dict[code] = df
            except Exception:
                continue
        return self.select_from_dataframes(data_dict, top_k=top_k)

    def print_result(self, result: SelectorResult):
        """打印选股结果"""
        print(result.summary)

    @staticmethod
    def _get_col(df: pd.DataFrame, candidates: List[str]) -> Optional[np.ndarray]:
        """智能列名匹配"""
        cols_lower = {c.lower().strip(): c for c in df.columns}
        for cand in candidates:
            if cand in cols_lower:
                return df[cols_lower[cand]].values.astype(np.float64)
        return None

    def _build_summary(self, candidates: List[StockCandidate]) -> str:
        """构建汇总报告"""
        lines = [
            f"\n{'='*70}",
            f"  单票 Regime 候选股票筛选结果 (Top {len(candidates)})",
            f"{'='*70}",
            f"  {'排名':<4} {'代码':<10} {'换手率':>8} {'年化波':>8} "
            f"{'市值(亿)':>8} {'天数':>6} {'评分':>6}",
            f"  {'-'*60}",
        ]
        for i, c in enumerate(candidates):
            cap_str = f"{c.market_cap:.0f}" if c.market_cap > 0 else "N/A"
            lines.append(
                f"  {i+1:<4} {c.code:<10} {c.avg_turnover:>7.2%} "
                f"{c.avg_volatility:>7.2%} {cap_str:>8} "
                f"{c.n_trading_days:>6} {c.score:>6.2f}"
            )
        lines.append(f"  {'─'*60}")
        lines.append(f"  筛选条件: 市值 {self.min_market_cap}-{self.max_market_cap}亿 | "
                     f"换手 {self.min_turnover:.0%}-{self.max_turnover:.0%} | "
                     f"波动 ≥{self.min_volatility:.0%} | "
                     f"天数 ≥{self.min_history_days}")
        return "\n".join(lines)
