"""
Pipeline 模块
============
单票 Regime-Adaptive 因子挖掘完整流水线。

七段式架构:
  Stage 1: StockSelector       — 选票（小市值 + 高波动 + 流动性过滤）
  Stage 2: DataSplitter         — 数据时序拆分（train/val/test）
  Stage 3: RegimeSplitter       — Regime 检测 + 标签
  Stage 4: PerRegimeFactorMiner — 分 Regime 因子挖掘（GP + Template）
  Stage 5: FactorValidator      — 因子验证（IC稳定性 + 去重 + 中性化）
  Stage 6: RegimeBacktester     — Regime 切换回测
  Stage 7: AgentReview          — Agent 离线审查（可选）

主入口: SingleStockPipeline
"""

from factor_lab.pipeline.pipeline import SingleStockPipeline, PipelineResult
from factor_lab.pipeline.factor_analyzer import FactorAnalyzer, FactorAnalysisReport
from factor_lab.pipeline.agent_review import AgentReview, ReviewReport

__all__ = ["SingleStockPipeline", "PipelineResult",
           "FactorAnalyzer", "FactorAnalysisReport",
           "AgentReview", "ReviewReport"]
