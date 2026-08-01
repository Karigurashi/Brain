# Factor Lab — Regime-Adaptive 因子挖掘

> 不同市场状态下用不同因子。

## 结构

```
factorLab/
├── factor_lab/                    # 核心库
│   ├── config.py                  # 配置
│   ├── operators.py               # 向量运算符
│   ├── data_pipeline.py           # 数据管线
│   ├── regime_detector.py         # Regime检测
│   ├── factor_miner.py            # 因子挖掘
│   └── evaluation.py              # 评估 + 回测
├── scripts/
│   └── run_single_stock_miner.py  # 入口
├── data/
│   └── 300442_daily.csv
├── requirements.txt
└── README.md
```

## 运行

```bash
pip install -r requirements.txt
python scripts/run_single_stock_miner.py --csv data/300442_daily.csv
```
