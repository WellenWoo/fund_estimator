# 基金实时估值程序

> 一个**用持仓 + 实时行情自行计算基金盘中估值**的 Python 程序。
> 不是从网站抄官方估值，而是用数据真正"算"出来。
> 初始验证标的：国泰创业板指数 (LOF) A，代码 `160223`，跟踪创业板指数 (399006)。
> 当前支持：**多基金通用**——根据基金类型自动匹配跟踪指数或采用主动基金估值算法。

---

## 多基金支持（多指数通用化 + 主动基金算法）

### 被动/指数型基金 (is_passive=true)

| 算法 | 说明 | MAE (pp) |
|---|---|---|
| v_index_full_no_cash ⭐ | 目标指数涨跌直接代理 | ~0.11 |

### 主动管理型基金 (is_passive=false)

| 算法 | 说明 | MAE (pp) |
|---|---|---|
| v_active_top10_blend ⭐ | top10 真实 + α×长尾×bench(csi1000) | ~0.75 |
| v_active_bench_csi1000 | 纯中证1000 基准代理 | ~0.71 |
| v_active_alpha | top10 + 长尾×(bench + 历史alpha) | ~0.72 |
| v_active_top10 | 纯前10大持仓还原 | ~2.15 |

### 自动检测流程

```
fund_code (如 160615)
    ↓ query_db_fund_info()
is_passive=True, tracker_index_code="000300"
    ↓ resolve_index_symbol("中证500", "000300")
index_symbol = "sh000300"
    ↓ load_common_inputs(index_symbol=...)
index_close = fetch_kline("sh000300")  # 中证500日线
    ↓ estimate(method="v_index_full_no_cash", index_change_pct=...)
估算净值 = T-1 NAV × (1 + 中证500涨跌%)
```

---

## 1. 项目目标

| 编号 | 任务 | 状态 |
|---|---|---|
| 1 | 搜索 GitHub 上基金估值相关代码仓，按国别/类型/算法分类评估 → `github_code.md` | ✅ |
| 2 | 检索学术/行业文献综述 → `paper_tel.md` | ✅ |
| 3 | 主要用 Python 编写，可结合其他语言 | ✅ |
| 4.1 | 对 LOF 160223 每日盘后估值并对比官方 NAV | ✅ |
| 4.2 | 误差超阈值则改进算法 | ✅ (改进两次，MAE 1.24pp → 0.13pp → 0.11pp) |

### 关键指标

```
样本区间  : 2026-04-25 ~ 2026-07-14 (53 个有效交易日 + 28 个非交易日跳过)
最佳算法  : 创业板指全代理（无 cash_drag）
MAE       : 0.1153 pp  (目标 < 0.5pp，优于目标 4.3 倍)
RMSE      : 0.1413 pp
Max err   : 0.3633 pp
Mean err  : +0.0036 pp (bias 几乎为 0)
超阈值     : 0/53       (全部合格)
```

---

## 2. 项目结构

```
code/fund_estimator/
├── README.md                          # 本文档
├── ITERATIONS.md                      # 算法迭代详细记录
├── REQUIREMENTS.md                    # 早期架构文档
│
├── core/
│   └── models.py                      # 数据模型: FundHolding / RealtimeQuote / NAVEstimate / NAVComparison
│
├── data_sources/
│   ├── cache.py                       # 本地 CSV 缓存层（TTL 24h）
│   ├── eastmoney/
│   │   ├── holding.py                 # 季报前 10 大持仓抓取（轻量）
│   │   ├── holdings_full.py           # 季报完整持仓 + 占净值比例
│   │   └── nav_history.py             # 历史净值 API（含分页）
│   ├── sina/
│   │   ├── realtime.py                # 实时行情 (hq.sinajs.cn, GBK)
│   │   └── history.py                 # 历史 K 线 (CN_MarketDataService)
│   ├── tencent/
│   │   └── realtime.py                # 备用实时 (qt.gtimg.cn, GBK)
│   └── tiantian/                      # 天天基金官方估值（仅做交叉校验）
│
├── estimators/
│   └── holdings_based.py              # 持仓还原法 (v_top10 / v_residual)
│
├── backtest/
│   ├── run_backtest.py                # 主回测入口
│   ├── run_index_backtest.py          # 创业板指代理回测
│   ├── iteration_tracker.py           # 多方法横向对比 + 选优
│   └── .cache/                        # 历史数据 + 回测结果
│
└── scripts/
    ├── estimate_160223.py             # 单次估值 CLI（实时盘中）
    ├── daily_close_estimate.py        # 每日盘后生产脚本
    ├── batch_daily_run.py             # 批量回放（多天）
    └── gen_dashboard.py               # HTML 可视化 dashboard

research/
├── github_code.md                     # 调研产物 1
└── paper_tel.md                       # 调研产物 2
```

---

## 3. 快速使用

### 3.1 单次估值（实时盘中）

```bash
cd /workspace
python3 -u code/fund_estimator/scripts/daily_close_estimate.py \
  --method v_index_full_no_cash \
  --trade-date 2026-07-13 \
  --fetch-official
```

输出：

```json
{
  "fund_code": "160223",
  "today": "2026-07-13",
  "t1_date": "2026-07-10",
  "t1_nav": 2.1318,
  "estimated_nav": 2.0657,
  "estimated_change_pct": -3.1023,
  "method": "v_index_full_no_cash",
  "official_nav": 2.068,
  "official_change_pct": -2.99
}

对比官方 NAV 2.068:  差异 -0.0023 (-0.1129%)
```

### 3.2 批量回放（多天）

```bash
python3 -u code/fund_estimator/scripts/batch_daily_run.py \
  --start 2026-04-25 --end 2026-07-13 \
  --method v_index_full_no_cash
```

### 3.3 横向对比（多算法）

```bash
python3 code/fund_estimator/backtest/iteration_tracker.py \
  --start 2026-04-25 --end 2026-07-13
```

### 3.4 可视化 dashboard

```bash
python3 code/fund_estimator/scripts/gen_dashboard.py
# → /workspace/dashboard.html
```

---

## 4. 数据流

```
┌──────────────┐  季报      ┌─────────────────────┐
│ 东方财富      │ ────────→ │ FundHolding (前 10)  │
│ FundArchives │  占净值%   │  + 股票仓位 (≈95%)   │
└──────────────┘            └─────────────────────┘
                                       │
                                       ↓
┌──────────────┐  实时行情   ┌─────────────────────┐
│ 新浪 hq.sinajs│ ────────→ │ RealtimeQuote       │
│ / 东方财富    │            │  (price, prev_close)│
└──────────────┘            └─────────────────────┘
                                       │
                                       ↓
                            ┌─────────────────────┐
                            │ v_index_full_no_cash│
                            │  T-1 NAV ×          │
                            │  (1 + 指数涨跌%)    │
                            └─────────────────────┘
                                       │
                                       ↓
                            ┌─────────────────────┐
                            │  估算 NAV            │
                            │  对比官方 NAV         │
                            │  记录 |error|        │
                            └─────────────────────┘
```

---

## 5. 核心算法对比

5 种算法在 53 个交易日（2026-04-25 ~ 2026-07-14）的回测结果：

| # | 算法 | MAE (pp) | RMSE | MAX | 超阈值 | 适用场景 |
|---|---|---:|---:|---:|---:|---|
| 1 | 纯持仓还原 top10 | 1.029 | 1.25 | 3.06 | **37/53** | 主动管理基金 |
| 2 | 创业板指全代理 (含 cash_drag) | 0.141 | 0.17 | 0.46 | 0/53 | 纯被动指数 |
| **3** | **创业板指全代理 (无 cash_drag) ⭐** | **0.115** | **0.14** | **0.36** | **0/53** | **LOF 160223 当前主推** |
| 4 | top10 + 创业板指混合 | 0.399 | 0.56 | 2.27 | 16/53 | 不推荐 |
| 5 | top10 + uncovered 代理 | 0.683 | 0.95 | 3.63 | 28/53 | 不推荐 |

> LOF 160223 是完全复制创业板指数的被动基金，所以"用指数直接代理"比"用前 10 大持仓还原"更准——后者只能覆盖 53% 仓位，剩下 47% 的"长尾"才是误差主要来源。

---

## 6. 关键发现（来自 paper_tel.md）

1. **DolphinDB IOPV 工程实现** 提供了"DELTAS 增量计算 + 状态引擎"的模板。
2. **嘉实中证 500ETF IOPV 实测** 误差均值 0% / 标准差 0.05%——这是 IOPV 精度上限锚。
3. **Elton/Gruber (1993) + Frino/Gallagher (2001)** 是基金持仓还原的标准理论框架。
4. **现金拖累 + 调仓窗口 + 停牌股 + 申赎冲击** 是误差的四大来源。
5. **对纯被动指数 LOF，"参考指数法"是最优解**，因为指数点位变化本身就是组合价值的无偏估计。

---

## 7. 改进路径

| 版本 | 目标 | 现状 |
|---|---|---|
| v1.0 | 持仓还原 (top10) | MAE 0.98pp (35/52 超阈值) |
| v1.5 | 创业板指代理 (含 cash_drag) | MAE 0.14pp (0/52) |
| **v1.6** | **创业板指代理 (无 cash_drag)** ⭐ | **MAE 0.11pp (0/52)** |
| v2.0 | 残差 + 现金拖累校准（ML） | TODO |
| v3.0 | 跨基金通用化 | TODO |
| v4.0 | 申赎冲击建模 | TODO |
| v5.0 | 多数据源容灾 | TODO |

详细见 [ITERATIONS.md](./ITERATIONS.md)。

---

## 8. 依赖与运行环境

- Python 3.11+ （标准库即可，仅 `urllib` + `re` + `json` + `dataclasses`）
- 网络：能访问东方财富 / 新浪 / 天天基金
- 无第三方依赖
- 缓存：本地文件系统，目录 `code/fund_estimator/.cache/`

---

## 9. 已知限制

1. **仅适用 A 股 LOF/ETF**：QDII / 港股 LOF 需扩展跨境模块（paper_tel §3.6）。
2. **数据源非官方**：所有接口均为公开可访问但未授权；长期使用需关注频率限制与接口变更。
3. **缓存 TTL 24h**：季报披露日请清空 cache 或加 force=True。
4. **停牌股 / 大宗交易 / 定增**未做精细建模（参考 paper_tel §6.2-6.3）。
5. **今天的 NAV 实际要 21:00 才公布**，盘后运行需要等到 21:00 才能 fetch-official 对比。

---

## 10. 接下来可能的扩展

- [ ] 多基金：把同一套框架用到跟踪沪深 300 / 中证 500 / 上证 50 的 LOF 上
- [ ] 多源容灾：新浪挂了自动切腾讯 / 东方财富
- [ ] 残差 dashboard：每天残差归因，识别"为什么有的日子误差偏大"
- [ ] 自动报警：连续 N 日 > 阈值 → 推送告警
- [ ] ML 校准：XGBoost 预测 daily residual，MAE 目标 < 0.05pp
- [ ] 实时 WebSocket 推送：盘中每 15 秒推一次估算
