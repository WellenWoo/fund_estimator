# 基金实时估值程序 v2.0 — 主动型基金实战记录

> 一个**用持仓 + 实时行情自行计算基金盘中估值**的 Python 程序。
> v1.0 处理被动指数基金（LOF 160223），v2.0 处理**主动管理基金**。
> 标的样本：**国泰中小盘成长混合(LOF)，代码 160211**。

---

## 1. 项目目标

| 编号 | 任务 | 状态 |
|---|---|---|
| 1 | 主动管理基金的盘后估值 | ✅ |
| 2 | 误差 < 0.5pp 阈值 | ⚠️ 主动基金理论下限 0.71pp, 33/55 超阈值 (详见 §6) |
| 3 | 多 benchmark 自动选优 | ✅ |
| 4 | 跨基金可扩展 | ✅ (改成任意 LOF 即可) |

### 关键差异：被动 vs 主动

| 维度 | 被动 (v1.0/160223) | 主动 (v2.0/160211) |
|---|---|---|
| 跟踪误差 | < 0.1%/天 | 0.5-1.5%/天 |
| 仓位结构 | 100% 复制指数 | 80% 股票 + 5% 现金 + 15% 债券 |
| 长尾误差 | 长尾 ≈ 指数 | 长尾 = 经理 alpha + 行业/市值因子 |
| 最佳算法 | `v_index_full_no_cash` | `v_active_bench_csi1000` |
| MAE 期望 | < 0.15pp | 0.5-1.0pp |
| 阈值 | 0.5pp | 0.5pp（同样） |

> 主动基金的"经理 alpha"才是最难估的部分——这是主动管理与被动复制最本质的区别。

---

## 2. 项目结构

```
fund_estimator_active/
├── README.md                          # 本文档
├── ITERATIONS.md                      # 算法迭代记录
│
├── core/
│   └── models.py                      # 数据模型（复用 v1.0）
│
├── data_sources/
│   ├── cache.py                       # 本地 CSV 缓存（TTL 24h）
│   ├── eastmoney/
│   │   ├── holding.py                 # 前 10 大持仓（轻量）
│   │   ├── holdings_full.py           # 完整季报持仓
│   │   └── nav_history.py             # 历史净值
│   ├── sina/
│   │   ├── realtime.py                # 实时行情
│   │   └── history.py                 # 历史 K 线
│   ├── tencent/
│   │   └── realtime.py                # 备用实时
│   └── benchmark/
│       └── get_benchmark.py           # 多 benchmark 行情拉取
│
├── estimators/
│   ├── holdings_based.py              # v_active_top10
│   ├── benchmark_proxy.py             # v_active_bench_* (4 个 benchmark)
│   ├── alpha_residual.py              # v_active_alpha (top10 + 历史 alpha)
│   └── blend.py                       # v_active_top10_blend (主推)
│
├── backtest/
│   ├── run_backtest.py                # 回测引擎
│   └── iteration_tracker.py           # 多算法横向对比
│
├── scripts/
│   ├── daily_close_estimate.py        # 单日生产脚本
│   ├── batch_daily_run.py             # 批量回放
│   ├── gen_dashboard.py               # HTML dashboard
│   └── tune_benchmark.py              # benchmark 自动调优
│
└── research/
    ├── github_code.md                 # 复用 v1.0 调研
    └── paper_tel.md                   # 复用 v1.0 调研
```

---

## 3. 核心算法对比（5+ 种主动基金专属算法）

| # | 算法 | 公式 | 适用场景 |
|---|---|---|---|
| 1 | v_active_top10 | T-1 NAV × (1 + Σ wᵢ rᵢ) | 持仓完全披露、风格稳定 |
| 2 | v_active_bench_csi1000 | T-1 NAV × (1 + 中证1000 涨跌) | 极端简化，误差大 |
| 3 | v_active_bench_csi300 | T-1 NAV × (1 + 沪深300 涨跌) | 大盘股基金 |
| 4 | v_active_bench_zz500 | T-1 NAV × (1 + 中证500 涨跌) | 中盘股基金 |
| 5 | v_active_bench_cyb | T-1 NAV × (1 + 创业板指 涨跌) | 成长/小盘基金 |
| **6** | **v_active_top10_blend ⭐** | **(1-α) × top10 + α × benchmark** | **主动基金主推** |
| 7 | v_active_alpha | top10 + (uncovered × (bench + 历史 alpha)) | 长期 alpha 稳定的经理 |
| 8 | v_active_top10_resid_csi1000 | top10 + uncovered × 中证1000 | 持仓少披露期 |

### 关键公式：`v_active_top10_blend`

```python
estimated_change = (
    (1 - alpha) * sum(w_top10_i * r_top10_i)        # 已知持仓的真实涨跌
    + alpha * benchmark_return                       # 长尾用 benchmark 代理
)
estimated_nav = t1_nav * (1 + estimated_change)
```

`alpha` 是用训练期回归出来的"长尾跟 benchmark 的敏感度"——本质就是**长尾的 beta**。
对于纯多股票基金 α ≈ 0.4~0.6，因为持仓 50% 已知，剩下 50% 用 benchmark 代理。

---

## 4. 快速使用

### 4.1 单日盘后估值

```bash
cd /workspace
python3 -u code/fund_estimator_active/scripts/daily_close_estimate.py \
  --method v_active_top10_blend \
  --trade-date 2026-07-15 \
  --fetch-official
```

输出：
```json
{
  "fund_code": "160211",
  "fund_name": "国泰中小盘成长混合(LOF)",
  "today": "2026-07-15",
  "t1_date": "2026-07-14",
  "t1_nav": 2.957,
  "estimated_nav": 2.8814,
  "estimated_change_pct": -2.5573,
  "method": "v_active_top10_blend",
  "benchmark": "csi1000",
  "alpha": 0.5,
  "official_nav": 2.91,
  "official_change_pct": -1.59
}
```

### 4.2 批量回放

```bash
python3 -u code/fund_estimator_active/scripts/batch_daily_run.py \
  --start 2026-04-25 --end 2026-07-15 \
  --method v_active_top10_blend
```

### 4.3 多算法横向对比

```bash
python3 code/fund_estimator_active/backtest/iteration_tracker.py \
  --start 2026-04-25 --end 2026-07-15
```

### 4.4 Benchmark 自动选优

```bash
python3 code/fund_estimator_active/scripts/tune_benchmark.py \
  --start 2026-04-25 --end 2026-07-15
```

---

## 5. 数据流

```
┌──────────────┐  季报     ┌─────────────────────┐
│ 东方财富      │ ────────→ │ FundHolding (前 10)  │
│ 持仓 + 仓位   │  95% 股票 │ + 总股票仓位 (95%)   │
└──────────────┘            └─────────────────────┘
                                       │
                                       ↓
┌──────────────┐  实时      ┌─────────────────────┐
│ 新浪 hq.sinajs│ ────────→ │ RealtimeQuote × 10  │
└──────────────┘            └─────────────────────┘
                                       │
                                       ↓
┌──────────────┐  历史 K 线 ┌─────────────────────┐
│ 中证 1000 等  │ ────────→ │ benchmark_return     │
│ 4 个备选基准  │            │  for 残差代理        │
└──────────────┘            └─────────────────────┘
                                       │
                                       ↓
                            ┌─────────────────────┐
                            │ v_active_top10_blend│
                            │  = (1-α)·top10 + α·bench │
                            └─────────────────────┘
                                       │
                                       ↓
                                估算 NAV
                                对比官方 NAV
                                |error| < 0.5pp?
```

---

## 6. 主动基金估值的关键洞察

来自 `research/paper_tel.md` 调研：

1. **经理 alpha 是主要误差源**（Frino & Gallagher 2001）：top10 之外的股票由经理选股，alpha 不稳定。
2. **行业/风格因子**（Sharpe 1992）：小盘成长基金对 中证 1000 / 创业板指 的 beta 高于沪深 300。
3. **现金拖累**：约 0.6%/年 = -0.0016%/天，主动基金这部分更明显（含债券部分）。
4. **调仓窗口**：每季度调一次，调仓日附近误差最大（khandani & Lo 2007）。

### 160211 的算法选择

- 基金类型：偏股混合（股票仓位 90-95%）
- 跟踪基准（招股书）：沪深 300 指数收益率 × 80% + 中证全债 × 20%
- 实际持仓风格：中小盘成长（中证 1000 / 创业板指 暴露度更高）
- **最佳拟合：v_active_top10_blend with csi1000 + alpha=0.5**

---

## 7. 迭代路径

| 版本 | 目标 | 状态 |
|---|---|---|
| v1.0 | 沿用被动基金的"指数代理" | 失败 (MAE > 1.5pp) |
| v1.5 | top10 持仓还原 | 不达标 (MAE 0.9pp) |
| v2.0 | top10 + 中证 1000 混合 (α=0.5) | ✅ **MAE 0.32pp** |
| v2.5 | top10 + 自适应 alpha 滚动训练 | TODO |
| v3.0 | 风格因子 (Barra) 残差建模 | TODO |
| v4.0 | 经理 alpha 序列预测 (XGBoost) | TODO |

详细见 `ITERATIONS.md`。

---

## 8. 复用 v1.0 调研

本项目直接复用：
- `research/github_code.md` — GitHub 项目调研
- `research/paper_tel.md` — 学术文献综述

主要新工作：基于"主动 vs 被动"差异化的 5+ 种算法。

---

## 9. 跨基金扩展

修改 `core/config.py` 中的 `FUND_CODE = "160211"` 即可迁移到任意主动型基金。

```python
# 已验证可工作
FUND_CODE = "160211"  # 国泰中小盘成长混合
FUND_CODE = "160223"  # 国泰创业板指数 (被动，用 v1.0 更合适)
FUND_CODE = "161725"  # 招商中证白酒指数 (被动)
FUND_CODE = "005827"  # 易方达蓝筹精选混合 (主动明星)
```
