"""
因子验证 + 深度分析详细报告
输出：每因子完整指标 + 可视化图表
"""
import sys
sys.path.insert(0, ".")

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from factor_lab.pipeline import SingleStockPipeline

# ── 跑 Pipeline ──
pipeline = SingleStockPipeline(preset="quick", verbose=False)
result = pipeline.run_pipeline("data/300442_daily.csv", "300442")

vr = result.validation_result
ar = result.analysis_report
sr = result.split_result

if vr is None:
    print("No validation result!")
    sys.exit(0)

datetime_dates = [str(d) for d in result.dates]

# ================================================================
# 1. 文本报告
# ================================================================
print("=" * 80)
print("  因子验证 & 深度分析 完整报告")
print("=" * 80)

for ri, flist in vr.passed.items():
    print(f"\n{'─'*80}")
    print(f"  Regime {ri} — 通过因子: {len(flist)} 个")
    print(f"{'─'*80}")

    for f in flist:
        name = f"{f.name}_R{ri}"
        print(f"\n  >>> {name} <<<")
        print(f"    公式:       {f.expression or f.name}")
        print(f"    类别:       {f.category}")
        print(f"    Train IC:   {f.train_ic:+.4f}")
        print(f"    Val IC:     {f.test_ic:+.4f}")
        print(f"    ICIR:       {f.icir:+.4f}")
        decay = f.train_ic * f.test_ic
        print(f"    方向一致性: {'一致' if decay > 0 else '反转!'}")
        if abs(f.train_ic) > 0.01:
            ic_decay_pct = (abs(f.train_ic) - abs(f.test_ic)) / abs(f.train_ic)
            print(f"    IC衰减率:   {ic_decay_pct:+.1%}")

        # ── 深度分析 ──
        dec = ar.ic_decay_results.get(name)
        wf = ar.walk_forward_results.get(name)
        st = ar.stratified_results.get(name)

        if dec:
            print(f"\n    [IC衰减分析]")
            print(f"    多周期IC:   ", end="")
            for h, ic in zip(dec.horizons, dec.ic_values):
                print(f"{h}d={ic:+.4f}  ", end="")
            print(f"\n    半衰期:     {dec.half_life:.1f} 天")
            print(f"    最优周期:   {dec.optimal_horizon} 天")
            print(f"    拟合R2:     {dec.r_squared:.3f}")

        if wf:
            print(f"\n    [Walk-Forward 验证]")
            print(f"    窗口数:     {wf.n_windows}")
            print(f"    各窗口IC均值:{wf.ic_mean:+.4f}")
            print(f"    IC标准差:   {wf.ic_std:.4f}")
            print(f"    ICIR:       {wf.icir:.3f}")
            print(f"    IC>0占比:   {wf.ic_positive_ratio:.1%}")
            print(f"    方向稳定性: {wf.ic_sign_stability:.1%}")
            print(f"    通过:       {wf.passed}")

        if st:
            print(f"\n    [分层回测]")
            print(f"    五分位收益: Q1={st.quintile_returns[0]:+.3%}  "
                  f"Q2={st.quintile_returns[1]:+.3%}  "
                  f"Q3={st.quintile_returns[2]:+.3%}  "
                  f"Q4={st.quintile_returns[3]:+.3%}  "
                  f"Q5={st.quintile_returns[4]:+.3%}")
            print(f"    多空价差:   {st.long_short_spread:+.4f}")
            print(f"    单调性得分: {st.monotonicity:.2f}")
            print(f"    最优组胜率: {st.top_quintile_hit_rate:.1%}")
            print(f"    通过:       {st.passed}")

        verdict = ar.final_verdicts.get(name, "UNKNOWN")
        print(f"\n    >>> 综合判定: {verdict}")

# ── 淘汰因子 ──
if vr.rejected:
    print(f"\n{'─'*80}")
    print(f"  淘汰因子")
    print(f"{'─'*80}")
    for ri, rlist in vr.rejected.items():
        for f, reason in rlist:
            print(f"  [{f.name}] train_IC={f.train_ic:+.4f} → {reason}")

# ================================================================
# 2. 可视化
# ================================================================
if ar and ar.ic_decay_results:
    fig, axes = plt.subplots(2, 2, figsize=(14, 10))
    fig.suptitle(f"Factor Validation Report — {result.stock_code}", fontsize=14, fontweight="bold")

    # ── 图1: IC 衰减曲线 ──
    ax = axes[0, 0]
    for name, dec in ar.ic_decay_results.items():
        colors = {"PASS": "green", "FAIL": "red"}
        v = ar.final_verdicts.get(name, "FAIL")
        c = colors.get(v, "gray")
        ax.plot(dec.horizons, dec.ic_values, "o-", label=name, color=c, linewidth=2)
    ax.axhline(y=0, color="gray", linestyle="--", linewidth=0.5)
    ax.set_xlabel("Prediction Horizon (days)")
    ax.set_ylabel("IC (Spearman)")
    ax.set_title("IC Decay Curve")
    ax.legend(fontsize=7, loc="lower left")
    ax.grid(True, alpha=0.3)

    # ── 图2: Walk-Forward ICIR ──
    ax = axes[0, 1]
    names = list(ar.walk_forward_results.keys())
    icirs = [ar.walk_forward_results[n].icir for n in names]
    bars = ax.bar(range(len(names)), icirs, color=["green" if v >= 0.05 else "red" for v in icirs])
    ax.axhline(y=0.05, color="orange", linestyle="--", alpha=0.7, label="Min IR=0.05")
    ax.set_xticks(range(len(names)))
    ax.set_xticklabels([n.replace("_R", "_") for n in names], fontsize=7, rotation=45, ha="right")
    ax.set_ylabel("ICIR (WF)")
    ax.set_title("Walk-Forward ICIR")
    ax.grid(True, alpha=0.3, axis="y")
    ax.legend(fontsize=7)

    # ── 图3: 分层单调性 ──
    ax = axes[1, 0]
    for name, st in ar.stratified_results.items():
        v = ar.final_verdicts.get(name, "FAIL")
        ls = "-" if v == "PASS" else "--"
        alpha = 0.9 if v == "PASS" else 0.4
        ax.plot(range(1, 6), st.quintile_returns, "o-", label=name, linestyle=ls, alpha=alpha)
    ax.set_xlabel("Quintile (1=Lowest factor value)")
    ax.set_ylabel("Mean Forward Return")
    ax.set_title("Stratified Returns (Monotonicity Check)")
    ax.legend(fontsize=7, loc="upper left")
    ax.grid(True, alpha=0.3)

    # ── 图4: 综合雷达图 ──
    ax = axes[1, 1]
    verdicts = [ar.final_verdicts.get(n, "FAIL") for n in names]
    n_pass = verdicts.count("PASS")
    n_fail = verdicts.count("FAIL")
    ax.pie([n_pass, n_fail], labels=["PASS", "FAIL"],
           autopct="%1.1f%%", colors=["green", "red"],
           startangle=90, explode=(0.05, 0))
    ax.set_title(f"Overall Verdict ({len(names)} factors)")

    plt.tight_layout()
    plt.savefig("validation_report.png", dpi=150, bbox_inches="tight")
    print(f"\n\n  [Plot] Saved to validation_report.png")
    plt.close()

print("\nDone.")
