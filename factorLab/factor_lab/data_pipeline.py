"""
数据管线模块
===========
统一的数据加载、特征工程和预处理管线，支持两种模式：

  1. 本地模式 (LocalPipeline)  — 读取本地 CSV，单股分析
  2. 聚宽模式 (JQPipeline)      — 聚宽研究环境，多股票池

用法:
    from factor_lab.data_pipeline import LocalPipeline
    pipe = LocalPipeline("data/300442_daily.csv")
    features, returns, raw_data = pipe.run()
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass
from factor_lab.operators import (
    rolling_apply, rolling_mean, rolling_std, rolling_max, rolling_min,
    rolling_skew, rolling_kurt, ewm_mean, safe_nan_to_num,
)
from factor_lab.config import DataConfig


# ================================================================
# 特征工程: 单股行情 → 多维特征矩阵
# ================================================================

@dataclass
class FeatureSet:
    """特征集合容器"""
    features: Dict[str, np.ndarray]  # feature_name → array[n_samples]
    feature_names: List[str]         # 有序特征名列表
    matrix: np.ndarray              # (n_samples, n_features)
    raw_data: pd.DataFrame          # 原始行情数据


def build_features_from_ohlcv(
    open_: np.ndarray,
    high: np.ndarray,
    low: np.ndarray,
    close: np.ndarray,
    volume: np.ndarray,
    windows: Tuple[int, ...] = (1, 3, 5, 10, 20),
) -> FeatureSet:
    """
    从 OHLCV 数据构建完整特征集。

    特征类别:
      - 基础量价: open/high/low/close/gap/hl_range
      - 收益率: 多周期 ret_xd, log_ret
      - 波动率: 多周期 vol_xd, atr, hl_vol
      - 均线系统: ma, macd, ma_ratio
      - 成交量: vol_ma, rel_vol, obv, vwap
      - K线形态: body, wick, body_ratio
      - 高阶矩: skew, kurt
      - 布林带: bb_position, dist_hh, dist_ll
      - 动量: roc, zscore, ret_range

    Args:
        open_, high, low, close, volume: 日线 OHLCV
        windows: 多周期窗口列表

    Returns:
        FeatureSet 包含特征字典、名称列表、矩阵和原始数据
    """
    n = len(close)
    F: Dict[str, np.ndarray] = {}

    # ── 基础量价 ──
    F["open"] = open_
    F["high"] = high
    F["low"] = low
    F["close"] = close
    F["gap"] = np.r_[0.0, open_[1:] - close[:-1]]
    F["hl_range"] = high - low

    # ── 收益率 ──
    for w in windows:
        ret = np.full(n, np.nan)
        ret[w:] = close[w:] / close[:-w] - 1.0
        ret[:w] = 0.0
        F[f"ret_{w}d"] = ret

    log_ret = np.r_[0.0, np.log(close[1:] / close[:-1])]
    F["log_ret"] = log_ret

    # ── 波动率 ──
    for w in [w for w in windows if w >= 5]:
        F[f"vol_{w}d"] = rolling_std(log_ret, w)

    tr = np.maximum(high - low, np.maximum(
        np.abs(high - np.roll(close, 1)),
        np.abs(low - np.roll(close, 1))
    ))
    F["atr_14"] = rolling_mean(tr, 14)
    F["hl_vol_20"] = rolling_std(np.log(high / low), 20)

    # ── 均线系统 ──
    for w in [w for w in [5, 10, 20, 60] if w <= n]:
        F[f"ma_{w}d"] = rolling_mean(close, w)

    if "ma_5d" in F and "ma_20d" in F:
        F["ma5_ma20"] = F["ma_5d"] / (F["ma_20d"] + 1e-8) - 1.0
    if "ma_10d" in F and "ma_60d" in F:
        F["ma10_ma60"] = F["ma_10d"] / (F["ma_60d"] + 1e-8) - 1.0

    # ── MACD ──
    ema12 = ewm_mean(close, 12)
    ema26 = ewm_mean(close, 26)
    F["macd"] = ema12 - ema26
    F["macd_signal"] = ewm_mean(F["macd"], 9)
    F["macdh"] = F["macd"] - F["macd_signal"]

    # ── 动量 ──
    for w in [5, 10, 20]:
        F[f"roc_{w}"] = close / np.roll(close, w) - 1.0

    # ── 成交量 ──
    for w in [5, 20]:
        F[f"vol_ma_{w}d"] = rolling_mean(volume, w)
    F["rel_vol"] = volume / (F["vol_ma_20d"] + 1e-8)
    F["obv"] = np.cumsum(volume * np.sign(np.r_[0.0, np.diff(close)]))
    F["vwap"] = np.cumsum(close * volume) / (np.cumsum(volume) + 1e-8)

    # ── K线形态 ──
    F["body"] = np.abs(close - open_)
    F["upper_wick"] = high - np.maximum(close, open_)
    F["lower_wick"] = np.minimum(close, open_) - low
    F["body_ratio"] = F["body"] / (F["hl_range"] + 1e-8)
    F["wick_body_r"] = (F["upper_wick"] + F["lower_wick"]) / (F["body"] + 1e-8)

    # ── 高阶矩 ──
    for w in [20]:
        F[f"skew_{w}d"] = rolling_skew(log_ret, w)
        F[f"kurt_{w}d"] = rolling_kurt(log_ret, w)

    # ── 标准化 / 布林 ──
    F["zscore_20"] = (close - rolling_mean(close, 20)) / (rolling_std(close, 20) + 1e-8)
    F["max_ret_20"] = rolling_max(log_ret, 20)
    F["min_ret_20"] = rolling_min(log_ret, 20)
    F["ret_range_20"] = F["max_ret_20"] - F["min_ret_20"]

    # ── 滞后 ──
    for w in [1, 3, 5, 10]:
        F[f"close_lag_{w}d"] = np.roll(close, w)

    # ── 通道 ──
    for w in [10, 20]:
        F[f"hh_{w}d"] = rolling_max(high, w)
        F[f"ll_{w}d"] = rolling_min(low, w)

    F["bb_position"] = (close - F["ll_20d"]) / (F["hh_20d"] - F["ll_20d"] + 1e-8)
    F["dist_hh20"] = F["hh_20d"] / (close + 1e-8) - 1.0
    F["dist_ll20"] = close / (F["ll_20d"] + 1e-8) - 1.0

    # ── 衍生特征 ──
    F["true_range"] = tr
    F["vol_contract"] = -(F["hl_vol_20"] - rolling_mean(F["hl_vol_20"], 60))
    F["range_compress"] = -(F["hl_vol_20"] - np.roll(F["hl_vol_20"], 60)) / (
        np.roll(F["hl_vol_20"], 60) + 1e-8
    )
    F["tr_narrow"] = -(tr / (rolling_mean(tr, 20) + 1e-8) - 1.0)
    F["obv_z"] = (F["obv"] - rolling_mean(F["obv"], 20)) / (rolling_std(F["obv"], 20) + 1e-8)
    F["vwap_div"] = close / (F["vwap"] + 1e-8) - 1.0
    F["ema_slope"] = (F["ma_5d"] - F["ma_60d"]) / (F["ma_60d"] + 1e-8)
    F["vol_dry"] = -(F["rel_vol"] - 1.0)

    # ── 组装 ──
    feature_names = sorted(F.keys())
    matrix = safe_nan_to_num(np.column_stack([F[k] for k in feature_names]))

    return FeatureSet(
        features=F,
        feature_names=feature_names,
        matrix=matrix,
        raw_data=pd.DataFrame({"open": open_, "high": high, "low": low,
                               "close": close, "volume": volume}),
    )


# ================================================================
# 前向收益构造
# ================================================================

def build_forward_returns(
    close: np.ndarray,
    prediction_days: int = 10,
) -> np.ndarray:
    """
    构造前向收益率目标。

    Args:
        close: 收盘价序列
        prediction_days: 预测期天数

    Returns:
        target[n] = close[n+prediction_days] / close[n] - 1
        末尾 prediction_days 天为 NaN
    """
    n = len(close)
    target = np.full(n, np.nan)
    target[:-prediction_days] = close[prediction_days:] / close[:-prediction_days] - 1.0
    return target


# ================================================================
# 本地数据管线
# ================================================================

class LocalPipeline:
    """本地单股数据管线 —— 读取 CSV 或从 Tushare 拉取，构建特征 + 目标"""

    def __init__(
        self,
        csv_path: str,
        prediction_days: int = 10,
        train_ratio: float = 0.6,
        random_seed: int = 42,
    ):
        """
        Args:
            csv_path: CSV 文件路径（需含 columns: trade_date, open, high, low, close, vol）
            prediction_days: 前向预测天数
            train_ratio: 训练集占比 (按时间序)
            random_seed: 随机种子
        """
        self.csv_path = csv_path
        self.prediction_days = prediction_days
        self.train_ratio = train_ratio
        self.random_seed = random_seed

    @classmethod
    def from_tushare(
        cls,
        token: str,
        ts_code: str,
        start: str = "20150101",
        end: str = "20301231",
        cache_dir: str = "data",
        prediction_days: int = 10,
        train_ratio: float = 0.6,
        random_seed: int = 42,
        force_refresh: bool = False,
    ) -> "LocalPipeline":
        """
        从 Tushare 拉取数据，缓存到本地 CSV，再走标准管线。

        Args:
            token: Tushare Pro token
            ts_code: 股票代码，如 '300442.SZ'
            start: 起始日期 'YYYYMMDD'
            end: 结束日期 'YYYYMMDD'
            cache_dir: CSV 缓存目录
            prediction_days: 前向预测天数
            train_ratio: 训练集占比
            random_seed: 随机种子
            force_refresh: 强制忽略缓存重新拉取

        Returns:
            LocalPipeline 实例（已拉取并缓存数据）
        """
        from factor_lab.data_fetcher import TushareFetcher
        fetcher = TushareFetcher(token=token, cache_dir=cache_dir)
        df = fetcher.fetch(ts_code, start, end, force_refresh=force_refresh)
        csv_path = fetcher._cache_path(ts_code)
        print(f"  [Tushare] {ts_code}: {len(df)} rows, {df['trade_date'].min().date()} ~ {df['trade_date'].max().date()}")
        return cls(
            csv_path=csv_path,
            prediction_days=prediction_days,
            train_ratio=train_ratio,
            random_seed=random_seed,
        )

    def run(self) -> Dict:
        """
        执行完整管线。

        Returns:
            dict with keys:
                - feature_set: FeatureSet
                - target: np.ndarray (前向收益率)
                - train_mask / test_mask: bool 数组
                - dates: 日期列表
                - close: 收盘价序列
        """
        # 1. 加载
        df = pd.read_csv(self.csv_path).sort_values("trade_date").reset_index(drop=True)
        col_map = {}
        for col in df.columns:
            col_lower = col.lower().strip()
            if "open" in col_lower: col_map["open"] = col
            elif "high" in col_lower: col_map["high"] = col
            elif "low" in col_lower: col_map["low"] = col
            elif "close" in col_lower and "pre" not in col_lower: col_map["close"] = col
            elif "vol" in col_lower: col_map["volume"] = col
            elif "trade_date" in col_lower or "date" in col_lower: col_map["date"] = col

        close = df[col_map["close"]].values.astype(np.float64)
        open_ = df[col_map["open"]].values.astype(np.float64)
        high = df[col_map["high"]].values.astype(np.float64)
        low = df[col_map["low"]].values.astype(np.float64)
        volume = df[col_map["volume"]].values.astype(np.float64)
        dates = df[col_map["date"]].astype(str).tolist()

        # 2. 特征工程
        feature_set = build_features_from_ohlcv(open_, high, low, close, volume)

        # 3. 目标
        target = build_forward_returns(close, self.prediction_days)

        # 4. 划分
        n = len(close)
        train_cut = int(n * self.train_ratio)
        train_mask = np.arange(n) < train_cut
        test_mask = ~train_mask

        # 5. 标准化 (在训练集上 fit)
        from sklearn.preprocessing import StandardScaler
        scaler = StandardScaler()
        X = feature_set.matrix.copy()
        X[train_mask] = scaler.fit_transform(X[train_mask])
        X[test_mask] = scaler.transform(X[test_mask])

        return {
            "feature_set": feature_set,
            "features_scaled": X,
            "target": target,
            "train_mask": train_mask,
            "test_mask": test_mask,
            "train_cut": train_cut,
            "dates": dates,
            "close": close,
            "open": open_,
            "high": high,
            "low": low,
            "volume": volume,
        }


# ================================================================
# 聚宽数据管线 (需在聚宽研究环境中运行)
# ================================================================

class JQPipeline:
    """
    聚宽多股票数据管线。

    注意: 此类依赖 jqdata，仅在聚宽研究环境中可用。
    """

    def __init__(self, config: Optional[DataConfig] = None):
        self.config = config or DataConfig()

    def get_eligible_stocks(
        self,
        eval_date,
        eligible_static: List[str],
        sec_df,
        st_raw,
    ) -> List[str]:
        """动态过滤：ST + 次新股"""
        from factor_lab.operators import safe_nan_to_num

        import datetime as dt
        cutoff = eval_date - dt.timedelta(days=self.config.min_list_days)
        d_str = eval_date.strftime('%Y-%m-%d')

        if d_str not in st_raw.index:
            return []
        st_row = st_raw.loc[d_str]

        result = []
        for s in eligible_static:
            if st_row.get(s, 1) == 1:  # ST 股
                continue
            if sec_df.loc[s, 'start_date'] > cutoff:  # 次新股
                continue
            result.append(s)
        return result

    @staticmethod
    def to_wide(prices, field: str, stocks_here: List[str]) -> pd.DataFrame:
        """面板数据 → 宽表 (index=code, columns=time)"""
        w = prices.pivot(index='code', columns='time', values=field)
        return w.reindex(stocks_here)

    @staticmethod
    def filter_suspended(vol_df, stocks_here, cls_df, hgh_df, low_df):
        """剔除停牌股（最后一日成交量为0）"""
        if vol_df.shape[1] > 0:
            active = vol_df.iloc[:, -1] > 0
            stocks_here = [s for s in stocks_here
                          if s in active.index and active.get(s, False)]
            cls_df = cls_df.loc[stocks_here]
            vol_df = vol_df.loc[stocks_here]
            hgh_df = hgh_df.loc[stocks_here]
            low_df = low_df.loc[stocks_here]
        return stocks_here, cls_df, vol_df, hgh_df, low_df

    @staticmethod
    def build_features_jq(cls_df, vol_df, hgh_df, low_df, fund_df) -> pd.DataFrame:
        """
        聚宽环境特征构建（11维精简版，适配多股票截面）。
        """
        feat = pd.DataFrame(index=cls_df.index)
        n_cols = cls_df.shape[1]

        feat['ret_1d'] = cls_df.iloc[:, -1] / cls_df.iloc[:, -2] - 1
        feat['ret_5d'] = (cls_df.iloc[:, -1] / cls_df.iloc[:, -6] - 1
                          if n_cols >= 6 else feat['ret_1d'])
        feat['ret_20d'] = (cls_df.iloc[:, -1] / cls_df.iloc[:, -21] - 1
                           if n_cols >= 21 else feat['ret_1d'])
        feat['amplitude'] = (hgh_df.iloc[:, -1] - low_df.iloc[:, -1]) / cls_df.iloc[:, -2]
        cap_s = fund_df['circulating_market_cap'].reindex(feat.index)
        feat['turnover'] = vol_df.iloc[:, -1] / (cap_s * 10000 + 1)
        if n_cols >= 6:
            vol_5d_avg = vol_df.iloc[:, -6:-1].mean(axis=1)
            feat['vol_ratio'] = vol_df.iloc[:, -1] / (vol_5d_avg + 1)
        else:
            feat['vol_ratio'] = 1.0
        feat['volume'] = vol_df.iloc[:, -1]
        feat['close'] = cls_df.iloc[:, -1]
        feat['cir_cap'] = cap_s
        feat['mktcap'] = fund_df['market_cap'].reindex(feat.index)
        feat['pb'] = fund_df['pb_ratio'].reindex(feat.index).fillna(0)
        return feat.dropna()
