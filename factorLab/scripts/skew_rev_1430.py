"""
skew_rev 14:30 实时信号
======================
每天 14:30 运行，取当天实时价代入因子，输出操作建议。

用法:
    python scripts/skew_rev_1430.py
    python scripts/skew_rev_1430.py --price 63.50   # 手动指定当前价
"""
import sys, os, json, subprocess
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np
import pandas as pd
from datetime import datetime
from factor_lab.operators import rolling_skew
from factor_lab.pipeline.daily_backtester import build_rolling_signal

SKILL_DIR = os.path.join(os.path.dirname(__file__), "..", "..", "workspace", "skills")
PYTHON = r"C:\Users\Administrator\AppData\Local\Programs\Python\Python314\python.exe"
APIKEY = "ht_27TVkQlszmTK9UzZOQcO43w4WokTJQ3VtmV9jn9Q6"


def get_realtime_price(code="300442"):
    """通过 query-indicator 获取实时价"""
    try:
        result = subprocess.run(
            [PYTHON, os.path.join(SKILL_DIR, "query-indicator", "query_indicator.py"),
             "queryIndicator", "--query", f"{code}实时价格"],
            capture_output=True, text=True, timeout=30,
            env={**os.environ, "HT_APIKEY": APIKEY},
        )
        data = json.loads(result.stdout)
        if data.get("ok"):
            import re
            nums = re.findall(r'[\d.]+', data["data"]["answer"])
            for n in reversed(nums):
                p = float(n)
                if 10 < p < 500:
                    return p
    except Exception as e:
        print(f"[WARN] 实时价获取失败: {e}")
    return None


def load_csv():
    csv_path = os.path.join(os.path.dirname(__file__), "..", "data", "300442_sz_daily.csv")
    df = pd.read_csv(csv_path)
    return df


def run(price_override=None):
    df = load_csv()
    close = df["close"].values
    dates = df["trade_date"].astype(str).values

    # 获取实时价
    if price_override:
        live_price = float(price_override)
    else:
        live_price = get_realtime_price()

    today_str = datetime.now().strftime("%Y%m%d")
    last_date = dates[-1]

    print(f"\n{'='*60}")
    print(f"  skew_rev 14:30 实时信号 — {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"  上次收盘: {last_date}  {close[-1]:.2f}")
    if live_price:
        print(f"  当前价格: {today_str}  {live_price:.2f}")
        # 临时追加当天数据
        close_ext = np.append(close, live_price)
    else:
        print(f"  [WARN] 无法获取实时价，使用最近收盘价")
        close_ext = close

    # 计算因子
    log_ret = np.r_[0.0, np.log(close_ext[1:] / close_ext[:-1])]
    skew_20d = rolling_skew(log_ret, 20)
    skew_rev = -skew_20d

    # 信号
    ic_direction = +1.0  # IC > 0
    signal = build_rolling_signal(skew_rev, ic_direction, lookback=20)

    # 最新信号
    latest_sig = signal[-1]
    latest_skew = skew_rev[-1]

    print(f"  skew_rev: {latest_skew:+.4f}")
    print(f"  信号分位: {latest_sig:.4f}")
    print(f"  {'='*60}")

    # 判断
    if np.isnan(latest_sig):
        print(f"  [ERROR] 信号无效")
        return

    price_display = live_price if live_price else close[-1]

    if latest_sig >= 0.60:
        print(f"  >>> 买入信号 <<<")
        print(f"  信号 {latest_sig:.2f} >= 0.60")
        print(f"  建议买入价: ~{price_display:.2f}")
        print(f"  止损: {price_display * 0.93:.2f} (-7%)")
        print(f"  最多持有: 5 个交易日")
    elif latest_sig < 0.35:
        print(f"  <<< 卖出/空仓信号 <<<")
        print(f"  信号 {latest_sig:.2f} < 0.35")
        print(f"  若持仓: 建议卖出 @ ~{price_display:.2f}")
        print(f"  若空仓: 继续观望")
    else:
        print(f"  --- 持有/观望 ---")
        print(f"  信号 {latest_sig:.2f} 在 [0.35, 0.60)")
        print(f"  若持仓: 继续持有")
        print(f"  若空仓: 继续观望")

    # 最近 5 个信号
    print(f"\n  最近 5 日信号:")
    for i in range(max(0, len(signal)-6), len(signal)):
        d = dates[i] if i < len(dates) else today_str
        s = signal[i]
        print(f"    {d}  sig={s:.4f}  skew_rev={skew_rev[i]:+.4f}")

    print()


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--price", type=float, default=None)
    args = parser.parse_args()
    run(price_override=args.price)
