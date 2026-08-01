"""
Pipeline 快速运行入口
=====================
单票 Regime-Adaptive 因子挖掘一键运行。

用法:
    cd factorLab
    python scripts/run_pipeline.py --csv data/300442_daily.csv
    python scripts/run_pipeline.py --tushare 300442.SZ

Preset 选择:
    python scripts/run_pipeline.py --preset quick    # 快速验证 (~2分钟)
    python scripts/run_pipeline.py --preset standard # 标准流程 (~8分钟)
    python scripts/run_pipeline.py --preset deep     # 深度搜索 (~30分钟)
"""

import sys
import os
import argparse

# ---- Windows UTF-8 编码修复 ----
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    os.environ["PYTHONIOENCODING"] = "utf-8"

sys.path.insert(0, ".")

from factor_lab.pipeline import SingleStockPipeline, PipelineResult


def _resolve_token(args) -> str:
    """解析 Tushare token：命令行 > 环境变量 > data/token.txt"""
    import os
    # 1. 命令行传入
    if args.tushare_token:
        return args.tushare_token
    # 2. 环境变量
    env_token = os.environ.get("TUSHARE_TOKEN", "")
    if env_token:
        return env_token
    # 3. 本地文件
    token_paths = ["data/token.txt", "token.txt"]
    for p in token_paths:
        if os.path.exists(p):
            with open(p) as f:
                return f.read().strip()
    sys.exit("No Tushare token found. Use --tushare-token, TUSHARE_TOKEN env, or data/token.txt")


def main():
    parser = argparse.ArgumentParser(description="FactorLab Regime Pipeline")
    parser.add_argument("--csv", type=str, default=None,
                        help="单股 OHLCV CSV 路径")
    parser.add_argument("--tushare", type=str, default=None, metavar="CODE",
                        help="从 Tushare 拉取（传入股票代码如 300442.SZ）")
    parser.add_argument("--tushare-token", type=str, default=None,
                        help="Tushare token（可选，默认读 TXT_PATH 环境变量或 data/token.txt）")
    parser.add_argument("--start", type=str, default="20250101",
                        help="Tushare 起始日期 YYYYMMDD")
    parser.add_argument("--end", type=str, default="20301231",
                        help="Tushare 结束日期 YYYYMMDD")
    parser.add_argument("--force-refresh", action="store_true",
                        help="强制重新从 Tushare 拉取（忽略缓存）")
    parser.add_argument("--preset", type=str, default="standard",
                        choices=["quick", "standard", "deep"],
                        help="预设模式")
    parser.add_argument("--code", type=str, default="300442",
                        help="股票代码")
    parser.add_argument("--pred-days", type=int, default=3,
                        help="预测天数")
    parser.add_argument("--agent", action="store_true",
                        help="运行 Stage 7 Agent 离线审查")
    args = parser.parse_args()

    # ── 解析数据源 ──
    if args.tushare:
        # Tushare 模式
        token = _resolve_token(args)
        data_source = f"Tushare:{args.tushare}"
    elif args.csv:
        data_source = f"CSV:{args.csv}"
    else:
        # 默认：尝试 data/ 下找 CSV
        import glob as _glob
        candidates = _glob.glob("data/*_daily.csv")
        if candidates:
            args.csv = candidates[0]
            data_source = f"CSV:{args.csv}"
        else:
            sys.exit("No --csv or --tushare specified, and no CSV found in data/")

    print(f"""
╔══════════════════════════════════════════════════════════════╗
║         FactorLab 单票 Regime-Adaptive 因子挖掘              ║
║  数据源: {data_source:<50s} ║
║  预设:   {args.preset:<8s}    预测: {args.pred_days} 天                   ║
╚══════════════════════════════════════════════════════════════╝
""")

    # ── 构建 Pipeline ──
    pipeline = SingleStockPipeline(
        preset=args.preset,
        prediction_days=args.pred_days,
        verbose=True,
    )

    # ── 运行 ──
    if args.tushare:
        result = pipeline.run_pipeline_from_tushare(
            token=token,
            ts_code=args.tushare,
            start=args.start,
            end=args.end,
            stock_code=args.code,
            force_refresh=args.force_refresh,
            run_agent_review=args.agent,
        )
    else:
        result = pipeline.run_pipeline(
            csv_path=args.csv,
            stock_code=args.code,
            run_agent_review=args.agent,
        )

    # ── 检查结果 ──
    print(f"\n  Stages completed: {result.stages_completed}")
    print(f"  Errors: {len(result.errors)}")

    if result.errors:
        print("  [ERRORS]")
        for stage, err in result.errors:
            print(f"    [{stage}] {err}")

    # ── 日级回测（Stage 7，唯一回测）──
    if result.daily_backtest_result:
        dbr = result.daily_backtest_result
        print(f"""
======================================================================
                 STAGE 7: DAILY BACKTEST
======================================================================
  Stock:     {result.stock_code}
  Total Ret: {dbr.total_return:>+8.2%}
  Annual Ret:{dbr.annual_return:>+8.2%}
  Sharpe:    {dbr.sharpe_ratio:>8.2f}
  Max DD:    {dbr.max_drawdown:>+8.2%}
  Win Rate:  {dbr.win_rate:>8.1%}
  Trades:    {dbr.n_trades:>5d}
  Avg Hold:  {dbr.avg_hold_days:>5.1f}d
  Buy&Hold:  {dbr.buy_and_hold_return:>+8.2%}
======================================================================
""")
    else:
        print("\n>> No backtest results.")

    print(f"  Total time: {result.elapsed_seconds:.1f}s")


if __name__ == "__main__":
    main()
