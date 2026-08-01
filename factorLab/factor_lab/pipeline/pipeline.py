"""
Pipeline 主编排器: SingleStockPipeline
=======================================
七段式单票 Regime-Adaptive 因子挖掘全流程。

架构:
  Stage 1: StockSelector       → 选票
  Stage 2: DataSplitter         → 数据拆分 (train/val/test)
  Stage 3: RegimeSplitter       → Regime 检测 + 标签
  Stage 4: PerRegimeFactorMiner → 分 Regime 因子挖掘
  Stage 5: FactorValidator      → 验证集因子过滤
  Stage 6: RegimeBacktester     → Regime 切换样本外回测
  Stage 7: AgentReview          → Agent 离线审查（可选）

用法:
    from factor_lab.pipeline import SingleStockPipeline

    pipeline = SingleStockPipeline(preset="standard")
    result = pipeline.run_pipeline("data/300442_daily.csv", run_agent_review=True)
"""

import numpy as np
import pandas as pd
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
import time

from factor_lab.pipeline.stock_selector import StockSelector, StockCandidate, SelectorResult
from factor_lab.pipeline.data_splitter import (
    DataSplitter, SplitResult,
    PurgedWalkForwardSplitter, WalkForwardSplitResult,
)
from factor_lab.pipeline.regime_splitter import RegimeSplitter, RegimeSplitResult
from factor_lab.pipeline.per_regime_miner import PerRegimeFactorMiner, PerRegimeMineResult
from factor_lab.pipeline.factor_validator import FactorValidator, ValidationResult
from factor_lab.pipeline.regime_backtester import RegimeBacktester, RegimeBacktestResult
from factor_lab.pipeline.daily_backtester import DailyBacktester, DailyBacktestResult, build_rolling_signal, verify_signal_ic
from factor_lab.pipeline.factor_analyzer import FactorAnalyzer, FactorAnalysisReport
from factor_lab.pipeline.agent_review import AgentReview, ReviewReport


# ================================================================
# 总结果
# ================================================================

@dataclass
class PipelineResult:
    """Pipeline 完整输出"""
    # ── 输入 ──
    stock_code: str = ""
    csv_path: str = ""

    # ── 各 Stage 结果 ──
    stock_candidate: Optional[StockCandidate] = None
    split_result: Optional[SplitResult] = None
    regime_result: Optional[RegimeSplitResult] = None
    mine_result: Optional[PerRegimeMineResult] = None
    validation_result: Optional[ValidationResult] = None
    backtest_result: Optional[RegimeBacktestResult] = None
    daily_backtest_result: Optional[DailyBacktestResult] = None
    analysis_report: Optional[FactorAnalysisReport] = None
    review_report: Optional[ReviewReport] = None

    # ── Walk-Forward 结果 ──
    wf_split_result: Optional[WalkForwardSplitResult] = None
    wf_backtests: List[DailyBacktestResult] = field(default_factory=list)
    wf_sharpe_distribution: List[float] = field(default_factory=list)
    wf_return_distribution: List[float] = field(default_factory=list)

    # ── 原始数据引用 ──
    features: Optional[Dict[str, np.ndarray]] = None
    target: Optional[np.ndarray] = None
    close: Optional[np.ndarray] = None
    dates: Optional[List[str]] = None

    # ── 元信息 ──
    elapsed_seconds: float = 0.0
    stages_completed: List[str] = field(default_factory=list)
    errors: List[Tuple[str, str]] = field(default_factory=list)

    def summary(self) -> str:
        """打印完整流水线汇总"""
        lines = [
            f"\n{'='*70}",
            f"  FactorLab Pipeline 运行报告",
            f"{'='*70}",
            f"  股票: {self.stock_code}",
            f"  耗时: {self.elapsed_seconds:.1f}s",
            f"  阶段: {' → '.join(self.stages_completed)}",
            f"",
        ]

        # Split
        if self.split_result:
            sr = self.split_result
            lines.append(f"  [数据拆分] 总{sr.n_total}天 → "
                         f"Train:{sr.n_train} Val:{sr.n_val} Test:{sr.n_test}")

        # Regime
        if self.regime_result:
            rr = self.regime_result
            lines.append(f"  [Regime检测] {rr.n_regimes}个状态")

        # Mining
        if self.mine_result:
            mr = self.mine_result
            lines.append(f"  [因子挖掘] {mr.n_total_factors}个因子 "
                         f"({mr.n_regimes_processed}个Regime)")

        # Validation
        if self.validation_result:
            vr = self.validation_result
            lines.append(f"  [因子验证] +{vr.n_passed} passed  -{vr.n_rejected} rejected")

        # Analysis
        if self.analysis_report and self.analysis_report.best_factor:
            ar = self.analysis_report
            lines.append(f"  [深度分析] Best={ar.best_factor} "
                         f"horizon={ar.best_horizon}d")

        # Backtest (Stage 7: 日级回测)
        if self.daily_backtest_result:
            dbr = self.daily_backtest_result
            lines.append(f"\n  {'='*50}")
            lines.append(f"  [Stage 7: 日级回测]")
            lines.append(f"  {dbr.summary()}")

        # Walk-Forward 聚合
        if self.wf_backtests:
            sharpes = self.wf_sharpe_distribution
            returns = self.wf_return_distribution
            wins = sum(1 for s in sharpes if s > 0)
            lines.append(f"\n  {'='*50}")
            lines.append(f"  [Walk-Forward 多窗口验证]")
            lines.append(f"  窗口数: {len(self.wf_backtests)}")
            lines.append(f"  Sharpe: mean={np.mean(sharpes):.2f}  std={np.std(sharpes):.2f}  "
                         f"min={np.min(sharpes):.2f}  max={np.max(sharpes):.2f}")
            lines.append(f"  Return: mean={np.mean(returns):.2%}  std={np.std(returns):.2%}")
            lines.append(f"  胜率: {wins}/{len(sharpes)} ({wins/len(sharpes):.0%}) 窗口 Sharpe>0")
            if wins == len(sharpes):
                lines.append(f"  ✅ 全窗口正向 — 因子稳定性极好")
            elif wins / len(sharpes) >= 0.6:
                lines.append(f"  ⚠️ 多数窗口正向 — 因子有一定稳定性")
            else:
                lines.append(f"  ❌ 多数窗口失效 — 因子可能是过拟合产物")

        # Errors
        if self.errors:
            lines.append(f"\n  [ERRORS]:")
            for stage, err in self.errors:
                lines.append(f"    [{stage}] {err}")

        lines.append(f"\n{'='*70}")
        return "\n".join(lines)


# ================================================================
# 主 Pipeline
# ================================================================

class SingleStockPipeline:
    """
    单票 Regime-Adaptive 因子挖掘 Pipeline。

    Presets:
      - "standard": 标准完整流程（推荐）
      - "quick":    快速验证（减少种群和代数）
      - "deep":     深度搜索（增大种群和代数）

    Example:
        pipeline = SingleStockPipeline(preset="standard")
        result = pipeline.run_pipeline("data/300442_daily.csv")
        print(result.summary())
    """

    def __init__(
        self,
        preset: str = "standard",
        # ── Stage 1: StockSelector ──
        min_market_cap: float = 30.0,
        max_market_cap: float = 300.0,
        min_turnover: float = 0.015,
        min_history_days: int = 500,
        # ── Stage 2: DataSplitter ──
        train_ratio: float = 0.60,
        val_ratio: float = 0.20,
        # ── Stage 3: RegimeSplitter ──
        regime_method: str = "kmeans",
        n_regimes: int = 4,
        # ── Stage 4: PerRegimeFactorMiner ──
        run_gp: bool = True,
        gp_population_size: int = 50,
        gp_generations: int = 25,
        run_template: bool = True,
        # ── Stage 5: FactorValidator ──
        ic_stability_threshold: float = 0.5,
        correlation_threshold: float = 0.7,
        min_absolute_ic: float = 0.02,
        # ── Stage 6: RegimeBacktester ──
        prediction_days: int = 3,
        signal_mode: str = "best_per_regime",
        # ── Stage 6: DailyBacktester ──
        run_daily_backtest: bool = True,
        daily_entry_threshold: float = 0.65,
        daily_exit_threshold: float = 0.50,
        daily_max_hold: int = 10,
        daily_stop_loss: float = -0.07,
        # ── Stage 5.5: FactorAnalyzer ──
        run_factor_analysis: bool = True,
        n_walk_forward_windows: int = 5,
        # ── Stage 7: AgentReview ──
        agent_model_name: Optional[str] = None,
        agent_temperature: float = 0.3,
        # ── Walk-Forward ──
        use_walk_forward: bool = False,
        n_wf_splits: int = 5,
        purge_days: int = 20,
        embargo_days: int = 0,
        # ── 通用 ──
        random_seed: int = 42,
        verbose: bool = True,
    ):
        # ── Apply preset ──
        if preset == "quick":
            gp_population_size = 30
            gp_generations = 12
            n_regimes = 3
        elif preset == "deep":
            gp_population_size = 100
            gp_generations = 50
            n_regimes = 5

        # ── Init stages ──
        self.stock_selector = StockSelector(
            min_market_cap=min_market_cap,
            max_market_cap=max_market_cap,
            min_turnover=min_turnover,
            min_history_days=min_history_days,
        )
        self.data_splitter = DataSplitter(
            train_ratio=train_ratio,
            val_ratio=val_ratio,
        )
        self.regime_splitter = RegimeSplitter(
            method=regime_method,
            n_regimes=n_regimes,
            random_seed=random_seed,
        )
        self.factor_miner = PerRegimeFactorMiner(
            run_gp=run_gp,
            gp_population_size=gp_population_size,
            gp_generations=gp_generations,
            run_template=run_template,
            random_seed=random_seed,
            verbose=verbose,
        )
        self.factor_validator = FactorValidator(
            ic_stability_threshold=ic_stability_threshold,
            correlation_threshold=correlation_threshold,
            min_absolute_ic=min_absolute_ic,
            verbose=verbose,
        )
        self.regime_backtester = RegimeBacktester(
            prediction_days=prediction_days,
            signal_mode=signal_mode,
            verbose=verbose,
        )
        self.daily_backtester = DailyBacktester(
            entry_threshold=daily_entry_threshold,
            exit_threshold=daily_exit_threshold,
            max_hold_days=daily_max_hold,
            stop_loss=daily_stop_loss,
            verbose=verbose,
        )
        self.run_daily_backtest = run_daily_backtest
        self.daily_entry_threshold = daily_entry_threshold
        self.daily_exit_threshold = daily_exit_threshold
        self.daily_max_hold = daily_max_hold
        self.daily_stop_loss = daily_stop_loss
        # ── Walk-Forward ──
        self.use_walk_forward = use_walk_forward
        self.n_wf_splits = n_wf_splits
        self.purge_days = purge_days
        self.embargo_days = embargo_days
        if use_walk_forward:
            self.wf_splitter = PurgedWalkForwardSplitter(
                n_splits=n_wf_splits,
                train_ratio=train_ratio,
                purge_days=purge_days,
                embargo_days=embargo_days,
            )
        else:
            self.wf_splitter = None
        self.factor_analyzer = FactorAnalyzer(
            n_walk_forward_windows=n_walk_forward_windows,
            verbose=verbose,
        )
        self.run_factor_analysis = run_factor_analysis
        self.agent_review = AgentReview(
            model_name=agent_model_name,
            temperature=agent_temperature,
            verbose=verbose,
        )

        self.prediction_days = prediction_days
        self.random_seed = random_seed
        self.verbose = verbose

    # ── 完整流程 ──

    def run_pipeline(
        self,
        csv_path: str,
        stock_code: str = "",
        stages: Optional[List[str]] = None,
        run_agent_review: bool = False,
    ) -> PipelineResult:
        """
        运行完整 Pipeline。

        Args:
            csv_path: 单股 OHLCV CSV 路径
            stock_code: 股票代码
            stages: 要运行的阶段，默认全部:
                    ["select","split","regime","mine","validate","backtest"]
            run_agent_review: 是否运行 Stage 7 Agent 离线审查

        Returns:
            PipelineResult
        """
        if stages is None:
            stages = ["select", "split", "regime", "mine", "validate"]

        result = PipelineResult(
            stock_code=stock_code or csv_path,
            csv_path=csv_path,
        )
        t0 = time.time()

        # ── 加载数据 ──
        try:
            data = self._load_data(csv_path, prediction_days=self.prediction_days)
        except Exception as e:
            result.errors.append(("load", str(e)))
            result.elapsed_seconds = time.time() - t0
            return result

        result.features = data["features"]
        result.target = data["target"]
        result.close = data["close"]
        result.dates = data["dates"]

        # ── Stage 1: Select ──
        if "select" in stages:
            try:
                df = data["raw_df"]
                result.stock_candidate = self.stock_selector.evaluate_single(
                    df, code=stock_code)
                result.stages_completed.append("select")
            except Exception as e:
                result.errors.append(("select", str(e)))

        # ── Stage 2: Split ──
        if "split" in stages:
            try:
                result.split_result = self.data_splitter.split(
                    n=len(data["close"]),
                    dates=result.dates,
                )
                result.stages_completed.append("split")
                if self.verbose:
                    self.data_splitter.print_split(result.split_result)
            except Exception as e:
                result.errors.append(("split", str(e)))
                result.elapsed_seconds = time.time() - t0
                return result

        # ── Stage 3: Regime ──
        if "regime" in stages and result.split_result:
            try:
                sr = result.split_result
                result.regime_result = self.regime_splitter.fit_predict(
                    X=data["features_scaled"],
                    feature_names=list(data["features"].keys()),
                    target=data["target"],
                    train_mask=sr.train_mask,
                    val_mask=sr.val_mask,
                    test_mask=sr.test_mask,
                    verbose=self.verbose,
                )
                result.stages_completed.append("regime")
            except Exception as e:
                result.errors.append(("regime", str(e)))

        # ── Stage 4: Mine ──
        if "mine" in stages and result.regime_result and result.split_result:
            try:
                result.mine_result = self.factor_miner.mine(
                    features=data["features"],
                    target=data["target"],
                    regime_result=result.regime_result,
                    split_result=result.split_result,
                )
                result.stages_completed.append("mine")
            except Exception as e:
                result.errors.append(("mine", str(e)))

        # ── Stage 5: Validate ──
        if "validate" in stages and result.mine_result and result.regime_result:
            try:
                result.validation_result = self.factor_validator.validate(
                    mine_result=result.mine_result,
                    features=data["features"],
                    target=data["target"],
                    regime_result=result.regime_result,
                    close=data["close"],
                )
                result.stages_completed.append("validate")
            except Exception as e:
                result.errors.append(("validate", str(e)))

        # ── Stage 6: Factor Analysis（交易模拟）──
        if self.run_factor_analysis and result.validation_result and result.regime_result:
            try:
                result.analysis_report = self.factor_analyzer.analyze(
                    factors=result.validation_result.passed,
                    features=data["features"],
                    close=data["close"],
                    split_result=result.split_result,
                )
                result.stages_completed.append("analyze")
            except Exception as e:
                result.errors.append(("analyze", str(e)))

        # ── Stage 7: Daily Backtest（全自动：多因子×多周期×多参数，Val选优，Test一次）──
        if self.run_daily_backtest and result.validation_result:
            try:
                from factor_lab.operators import spearman_correlation
                sr = result.split_result
                close_arr = data["close"]

                # 收集所有通过验证的因子
                all_passed = []
                for ri, flist in result.validation_result.passed.items():
                    for f in flist:
                        if f.factor_values is not None:
                            all_passed.append(f)

                if not all_passed:
                    if self.verbose:
                        print("\n  [Daily BT] No valid factors to test")
                else:
                    # 全局最优追踪
                    best_overall_sharpe = -999
                    best_overall = None  # (factor_name, pred_days, entry, exit, mh, sl, signal_array)

                    # 尝试多个预测周期
                    for pred_days in [3, 5]:
                        fwd_ret = np.full(len(close_arr), np.nan)
                        fwd_ret[:-pred_days] = close_arr[pred_days:] / close_arr[:-pred_days] - 1.0

                        for factor in all_passed:
                            fv = factor.factor_values
                            name = factor.name

                            # Train IC（定信号方向）
                            tv = sr.train_mask & np.isfinite(fv) & np.isfinite(fwd_ret)
                            if tv.sum() < 15:
                                continue
                            train_ic = spearman_correlation(fv[tv], fwd_ret[tv])
                            if not np.isfinite(train_ic) or abs(train_ic) < 0.02:
                                continue

                            # 构建信号
                            sig_full = build_rolling_signal(fv, train_ic, lookback=20)
                            val_sig = sig_full.copy()
                            val_sig[~sr.val_mask] = np.nan

                            # Val 扫参
                            for entry in [0.60, 0.65, 0.70]:
                                for exit_t in [0.35, 0.40, 0.45]:
                                    for mh in [3, 5, 7]:
                                        for sl in [-0.05, -0.07, -0.10]:
                                            bt = DailyBacktester(entry, exit_t, mh, sl, verbose=False)
                                            r = bt.run(val_sig, close_arr, data["dates"], sr.val_mask)
                                            if r.n_trades >= 3 and r.sharpe_ratio > best_overall_sharpe:
                                                best_overall_sharpe = r.sharpe_ratio
                                                best_overall = (name, pred_days, entry, exit_t, mh, sl,
                                                                sig_full.copy(), r.total_return)

                    if best_overall is None:
                        if self.verbose:
                            print("\n  [Daily BT] No valid parameter combo found")
                    else:
                        best_name, best_pd, best_entry, best_exit, best_mh, best_sl, best_sig, best_val_ret = best_overall

                        if self.verbose:
                            print(f"\n  [Daily BT] AUTO selected:")
                            print(f"    Factor: {best_name}  pred_days={best_pd}")
                            print(f"    Params: entry={best_entry} exit={best_exit} max_hold={best_mh} sl={best_sl}")
                            print(f"    Val: ret={best_val_ret:+.2%}  sharpe={best_overall_sharpe:.2f}")

                        # Test 一次
                        test_sig = best_sig.copy()
                        test_sig[~sr.test_mask] = np.nan
                        bt_final = DailyBacktester(best_entry, best_exit, best_mh, best_sl, verbose=True)
                        result.daily_backtest_result = bt_final.run(
                            test_sig, close_arr, data["dates"], sr.test_mask)
                        result.stages_completed.append("daily_bt")

                        # ── 稳健性检测（滑动窗口）──
                        self._robustness_check(
                            best_sig, best_entry, best_exit, best_mh, best_sl,
                            close_arr, data["dates"], sr, result,
                        )

                        # ── Stage 7.5: Walk-Forward 多窗口验证 ──
                        if self.use_walk_forward and result.wf_split_result:
                            self._run_walk_forward_validation(
                                result=result,
                                best_sig=best_sig,
                                best_entry=best_entry,
                                best_exit=best_exit,
                                best_mh=best_mh,
                                best_sl=best_sl,
                                close_arr=close_arr,
                                data=data,
                            )
                            result.stages_completed.append("wf_validate")

            except Exception as e:
                result.errors.append(("daily_bt", str(e)))

        # ── Stage 8: Agent Review ──
        if run_agent_review:
            try:
                result.review_report = self.agent_review.review(result)
                result.stages_completed.append("review")
            except Exception as e:
                result.errors.append(("review", str(e)))

        result.elapsed_seconds = time.time() - t0

        if self.verbose:
            print(result.summary())

        return result

    # ── Tushare 模式 ──

    def run_pipeline_from_tushare(
        self,
        token: str,
        ts_code: str,
        start: str = "20150101",
        end: str = "20301231",
        stock_code: str = "",
        force_refresh: bool = False,
        stages: Optional[List[str]] = None,
        run_agent_review: bool = False,
    ) -> PipelineResult:
        """
        从 Tushare 拉取数据后运行完整 Pipeline。

        Args:
            token: Tushare Pro token
            ts_code: 股票代码，如 '300442.SZ'
            start: 起始日期 'YYYYMMDD'
            end: 结束日期 'YYYYMMDD'
            stock_code: 显示用的简短代码
            force_refresh: 强制重新拉取（忽略缓存）
            stages: 要运行的阶段
            run_agent_review: 是否运行 Agent 审查

        Returns:
            PipelineResult
        """
        from factor_lab.data_pipeline import LocalPipeline

        pipe = LocalPipeline.from_tushare(
            token=token,
            ts_code=ts_code,
            start=start,
            end=end,
            cache_dir="data",
            prediction_days=self.prediction_days,
            train_ratio=0.6,
            force_refresh=force_refresh,
        )
        return self.run_pipeline(
            csv_path=pipe.csv_path,
            stock_code=stock_code or ts_code,
            stages=stages,
            run_agent_review=run_agent_review,
        )

    # ── 简化版：直接给已加载的数据 ──

    def run_from_data(
        self,
        features: Dict[str, np.ndarray],
        target: np.ndarray,
        close: np.ndarray,
        dates: List[str],
        features_scaled: Optional[np.ndarray] = None,
        stock_code: str = "",
        run_agent_review: bool = False,
    ) -> PipelineResult:
        """
        直接从已加载的数据运行 Pipeline（跳过 Stage 1 数据加载）。

        适用于已经在外部加载和预处理好的数据。
        """
        result = PipelineResult(stock_code=stock_code)
        t0 = time.time()

        result.features = features
        result.target = target
        result.close = close
        result.dates = dates

        n = len(close)

        # Split
        result.split_result = self.data_splitter.split(n=n, dates=dates)
        sr = result.split_result
        if self.verbose:
            self.data_splitter.print_split(sr)

        # Scale features if not provided
        if features_scaled is None:
            from sklearn.preprocessing import StandardScaler
            X = np.column_stack([features[k] for k in sorted(features.keys())])
            from factor_lab.operators import safe_nan_to_num
            X = safe_nan_to_num(X)
            scaler = StandardScaler()
            X[sr.train_mask] = scaler.fit_transform(X[sr.train_mask])
            X[~sr.train_mask] = scaler.transform(X[~sr.train_mask])
            features_scaled = X

        # Regime
        result.regime_result = self.regime_splitter.fit_predict(
            X=features_scaled,
            feature_names=sorted(features.keys()),
            target=target,
            train_mask=sr.train_mask,
            val_mask=sr.val_mask,
            test_mask=sr.test_mask,
            verbose=self.verbose,
        )

        # Mine
        result.mine_result = self.factor_miner.mine(
            features=features,
            target=target,
            regime_result=result.regime_result,
            split_result=sr,
        )

        # Validate
        result.validation_result = self.factor_validator.validate(
            mine_result=result.mine_result,
            features=features,
            target=target,
            regime_result=result.regime_result,
            close=close,
        )

        # Analysis (Stage 5.5)
        if self.run_factor_analysis:
            try:
                result.analysis_report = self.factor_analyzer.analyze(
                    factors=result.validation_result.passed,
                    features=features,
                    close=close,
                    split_result=sr,
                )
            except Exception as e:
                result.errors.append(("analyze", str(e)))

        # Backtest (use optimal horizon from analysis)
        optimal_pred_days = prediction_days
        if result.analysis_report and result.analysis_report.best_horizon:
            optimal_pred_days = result.analysis_report.best_horizon
            if self.verbose:
                print(f"\n  [Backtest] Using optimal horizon={optimal_pred_days}d")
        if optimal_pred_days != prediction_days:
            self.regime_backtester.prediction_days = optimal_pred_days

        result.backtest_result = self.regime_backtester.run(
            validated_factors=result.validation_result.passed,
            features=features,
            target=target,
            close=close,
            dates=dates,
            regime_labels=result.regime_result.regime_labels,
            test_mask=sr.test_mask,
        )

        result.stages_completed = ["split", "regime", "mine", "validate"]

        # ── Stage 8: Agent Review ──
        if run_agent_review:
            try:
                result.review_report = self.agent_review.review(result)
                result.stages_completed.append("review")
            except Exception as e:
                result.errors.append(("review", str(e)))

        result.elapsed_seconds = time.time() - t0

        if self.verbose:
            print(result.summary())

        return result

    # ── 内部方法 ──

    def _robustness_check(
        self,
        sig: np.ndarray,
        entry: float,
        exit_t: float,
        max_hold: int,
        stop_loss: float,
        close_arr: np.ndarray,
        dates: List[str],
        sr: SplitResult,
        result: PipelineResult,
    ):
        """滑动窗口稳健性检测（已整合到 Walk-Forward 中，此处为占位）"""
        pass

    def _run_walk_forward_validation(
        self,
        result: PipelineResult,
        best_sig: np.ndarray,
        best_entry: float,
        best_exit: float,
        best_mh: int,
        best_sl: float,
        close_arr: np.ndarray,
        data: Dict,
    ):
        """
        Purged Walk-Forward 多窗口验证。

        核心逻辑:
          用同一因子 + 同一参数，在每个 Walk-Forward 窗口的
          纯样本外（Test）上独立回测。

          如果因子真的有效，它应该在大多数窗口上都表现良好；
          如果只在某一个窗口好，那就是过拟合。
        """
        wf = result.wf_split_result
        if wf is None or not wf.splits:
            return

        if self.verbose:
            print(f"\n{'='*60}")
            print(f"  Walk-Forward 多窗口验证")
            print(f"  {'='*60}")
            print(f"  固定参数: entry={best_entry} exit={best_exit} max_hold={best_mh} sl={best_sl}")
            print(f"  {'─'*60}")
            print(f"  {'窗口':<6s} {'区间':>24s} {'交易':>5s} {'收益':>8s} {'Sharpe':>7s} {'胜率':>7s}")
            print(f"  {'─'*60}")

        sharpes = []
        returns = []
        backtests = []

        for sp in wf.splits:
            # 仅用当前窗口的 test mask
            test_sig = best_sig.copy()
            test_sig[~sp.test_mask] = np.nan

            bt = DailyBacktester(best_entry, best_exit, best_mh, best_sl, verbose=False)
            r = bt.run(test_sig, close_arr, data["dates"], sp.test_mask)

            backtests.append(r)
            sharpes.append(r.sharpe_ratio if np.isfinite(r.sharpe_ratio) else 0.0)
            returns.append(r.total_return if np.isfinite(r.total_return) else 0.0)

            if self.verbose:
                test_range = f"{sp.test_start}→{sp.test_end}"
                print(f"  W{sp.window_index:<5d} {test_range:>24s} {r.n_trades:>5d} "
                      f"{r.total_return:>+7.1%} {r.sharpe_ratio:>+7.2f} {r.win_rate:>6.1%}")

        # ── 聚合统计 ──
        result.wf_backtests = backtests
        result.wf_sharpe_distribution = sharpes
        result.wf_return_distribution = returns

        if self.verbose:
            wins = sum(1 for s in sharpes if s > 0)
            print(f"  {'─'*60}")
            print(f"  Sharpe: mean={np.mean(sharpes):.2f}  std={np.std(sharpes):.2f}  "
                  f"min={np.min(sharpes):.2f}  max={np.max(sharpes):.2f}")
            print(f"  Return: mean={np.mean(returns):.2%}  std={np.std(returns):.2%}")
            print(f"  正向窗口: {wins}/{len(sharpes)} ({wins/len(sharpes):.0%})")
            if wins == len(sharpes):
                print(f"  ✅ 全窗口正向 — 因子稳定性极好")
            elif wins / len(sharpes) >= 0.6:
                print(f"  ⚠️ 多数窗口正向 — 因子有一定稳定性")
            else:
                print(f"  ❌ 多数窗口失效 — 因子可能是过拟合产物")
            print(f"  {'='*60}")

    @staticmethod
    def _load_data(csv_path: str, prediction_days: int = 3) -> Dict:
        """加载 + 特征工程 + 标准化"""
        from factor_lab.data_pipeline import (
            LocalPipeline, build_features_from_ohlcv, build_forward_returns,
        )
        from factor_lab.operators import safe_nan_to_num
        from sklearn.preprocessing import StandardScaler

        # 加载原始CSV
        df = pd.read_csv(csv_path).sort_values("trade_date").reset_index(drop=True)

        col_map = {}
        for col in df.columns:
            cl = col.lower().strip()
            if "open" in cl:
                col_map["open"] = col
            elif "high" in cl:
                col_map["high"] = col
            elif "low" in cl:
                col_map["low"] = col
            elif "close" in cl and "pre" not in cl:
                col_map["close"] = col
            elif "vol" in cl:
                col_map["volume"] = col
            elif "trade_date" in cl or "date" in cl:
                col_map["date"] = col

        close = df[col_map["close"]].values.astype(np.float64)
        open_ = df[col_map["open"]].values.astype(np.float64)
        high = df[col_map["high"]].values.astype(np.float64)
        low = df[col_map["low"]].values.astype(np.float64)
        volume = df[col_map["volume"]].values.astype(np.float64)
        dates = df[col_map["date"]].astype(str).tolist()

        # 特征工程
        feature_set = build_features_from_ohlcv(open_, high, low, close, volume)

        # 目标
        target = build_forward_returns(close, prediction_days=prediction_days)

        # 标准化 (先用临时 mask)
        n = len(close)
        temp_train = int(n * 0.6)
        train_mask_temp = np.arange(n) < temp_train

        X = feature_set.matrix.copy()
        scaler = StandardScaler()
        X[train_mask_temp] = scaler.fit_transform(X[train_mask_temp])
        X[~train_mask_temp] = scaler.transform(X[~train_mask_temp])

        return {
            "features": feature_set.features,
            "features_scaled": X,
            "target": target,
            "close": close,
            "dates": dates,
            "raw_df": df,
        }
