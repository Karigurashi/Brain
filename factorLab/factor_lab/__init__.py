"""
Factor Lab — A股 Regime-Adaptive 量化因子研究框架
==================================================

核心模块:
  config            — 统一配置管理
  operators         — 向量运算符 + 截面工具
  data_pipeline     — 数据管线 (本地CSV / 聚宽双模式)
  regime_detector   — Regime检测 + 退出分析
  factor_miner      — 因子挖掘 (GP / 模板)
  evaluation        — 因子评估 + 回测

用法:
  python scripts/run_single_stock_miner.py --csv data/300442_daily.csv

Author: Mango Quant
"""

__version__ = "2.0.0"
