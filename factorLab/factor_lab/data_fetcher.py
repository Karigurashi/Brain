"""
Tushare 数据获取模块
==================
封装 Tushare Pro API，按需拉取 A 股日线数据，自动缓存到本地 CSV。

用法:
    from factor_lab.data_fetcher import TushareFetcher

    fetcher = TushareFetcher(token="your_token")
    df = fetcher.fetch("300442.SZ", start="20200101", end="20260727")
    # 自动缓存到 data/{code}_daily.csv，下次读取直接走缓存
"""

import os
import numpy as np
import pandas as pd
from typing import Optional
from dataclasses import dataclass


@dataclass
class FetchResult:
    """拉取结果"""
    code: str
    rows: int
    start_date: str
    end_date: str
    csv_path: str          # 缓存文件路径
    from_cache: bool       # 是否来自缓存


class TushareFetcher:
    """Tushare 日线数据获取 + 本地缓存"""

    # Tushare 列 → 内部标准列
    COLUMN_MAP = {
        "ts_code": "ts_code",
        "trade_date": "trade_date",
        "open": "open",
        "high": "high",
        "low": "low",
        "close": "close",
        "pre_close": "pre_close",
        "change": "change",
        "pct_chg": "pct_chg",
        "vol": "vol",
        "amount": "amount",
    }

    def __init__(
        self,
        token: str,
        cache_dir: str = "data",
        cache_ttl_days: int = 1,   # 缓存有效期：1天内不重复拉取
    ):
        """
        Args:
            token: Tushare Pro token
            cache_dir: CSV 缓存目录
            cache_ttl_days: 缓存有效期（天），0=永不过期
        """
        import tushare as ts
        ts.set_token(token)
        self.pro = ts.pro_api()
        self.cache_dir = cache_dir
        self.cache_ttl_days = cache_ttl_days
        os.makedirs(cache_dir, exist_ok=True)

    # ----------------------------------------------------------------
    # 公开接口
    # ----------------------------------------------------------------

    def fetch(
        self,
        ts_code: str,
        start: str = "20150101",
        end: str = "20301231",
        force_refresh: bool = False,
    ) -> pd.DataFrame:
        """
        拉取单股日线，优先读缓存。

        Args:
            ts_code: 股票代码（Tushare格式），如 '300442.SZ'
            start: 起始日期 'YYYYMMDD'
            end: 结束日期 'YYYYMMDD'
            force_refresh: 强制忽略缓存重新拉取

        Returns:
            DataFrame，按 trade_date 升序，列名与现有 CSV 格式一致
        """
        csv_path = self._cache_path(ts_code)

        # 缓存命中
        if (not force_refresh) and self._cache_valid(csv_path):
            df = pd.read_csv(csv_path, parse_dates=["trade_date"])
            df = df.sort_values("trade_date").reset_index(drop=True)
            return df

        # 调 Tushare API
        df = self._fetch_from_api(ts_code, start, end)

        if len(df) == 0:
            raise RuntimeError(f"Tushare returned 0 rows for {ts_code} [{start}~{end}]")

        # 写入缓存
        df.to_csv(csv_path, index=False)

        return df

    def fetch_multiple(
        self,
        ts_codes: list,
        start: str = "20150101",
        end: str = "20301231",
        force_refresh: bool = False,
    ) -> dict:
        """
        批量拉取多只股票。

        Returns:
            dict: {ts_code: DataFrame}
        """
        import time
        results = {}
        for i, code in enumerate(ts_codes):
            try:
                results[code] = self.fetch(code, start, end, force_refresh)
            except Exception as e:
                print(f"  [WARN] {code} fetch failed: {e}")
                results[code] = pd.DataFrame()
            # Tushare 免费账户限频：每分钟约 200 次，保守间隔
            if i < len(ts_codes) - 1:
                time.sleep(0.3)
        return results

    def get_cache_info(self, ts_code: str) -> Optional[FetchResult]:
        """查看缓存状态"""
        csv_path = self._cache_path(ts_code)
        if not os.path.exists(csv_path):
            return None
        df = pd.read_csv(csv_path, parse_dates=["trade_date"])
        return FetchResult(
            code=ts_code,
            rows=len(df),
            start_date=str(df["trade_date"].min().date()),
            end_date=str(df["trade_date"].max().date()),
            csv_path=csv_path,
            from_cache=True,
        )

    # ----------------------------------------------------------------
    # 内部方法
    # ----------------------------------------------------------------

    def _cache_path(self, ts_code: str) -> str:
        """缓存路径: data/300442_daily.csv"""
        code_clean = ts_code.replace(".", "_").lower()
        return os.path.join(self.cache_dir, f"{code_clean}_daily.csv")

    def _cache_valid(self, csv_path: str) -> bool:
        """缓存是否有效（文件存在 + 未过期）"""
        if not os.path.exists(csv_path):
            return False
        if self.cache_ttl_days <= 0:
            return True
        mtime = os.path.getmtime(csv_path)
        age_days = (pd.Timestamp.now().timestamp() - mtime) / 86400
        return age_days < self.cache_ttl_days

    def _fetch_from_api(
        self, ts_code: str, start: str, end: str
    ) -> pd.DataFrame:
        """
        调用 Tushare pro.daily()，返回标准化 DataFrame。
        列名保持与现有 300442_daily.csv 一致（open/high/low/close/vol/amount）。
        """
        df = self.pro.daily(ts_code=ts_code, start_date=start, end_date=end)

        if df is None or len(df) == 0:
            return pd.DataFrame()

        # 列映射：保留标准列
        cols_keep = [c for c in self.COLUMN_MAP if c in df.columns]
        df = df[cols_keep].copy()

        # 排序：最旧→最新
        df = df.sort_values("trade_date").reset_index(drop=True)

        # 类型转换
        for col in ["open", "high", "low", "close", "pre_close", "change", "pct_chg", "vol", "amount"]:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")

        return df


# ================================================================
# 便捷函数：一行拉取
# ================================================================

def quick_fetch(
    ts_code: str,
    token: str,
    start: str = "20150101",
    end: str = "20301231",
    cache_dir: str = "data",
) -> pd.DataFrame:
    """一行拉取数据（自动缓存）"""
    fetcher = TushareFetcher(token=token, cache_dir=cache_dir)
    return fetcher.fetch(ts_code, start, end)
