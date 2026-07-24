# fund_estimator_active 模块深度分析报告

## 摘要

本报告分析了 `code/fund_estimator_active` 子模块的三大核心组件：**完整持仓数据源**（holdings_full.py）、**主动基金回测引擎**（run_backtest.py）和**迭代跟踪器**（iteration_tracker.py）。实际回测结果基于基金 160211，时间窗口为 2026-04-25 ~ 2026-07-15，共 50 个交易日。8 种估算算法中，最佳 MAE 为 **0.7495pp**（v_active_top10_blend_csi1000），但整体误差范围较大，主要受极端行情日（如单日 -4.95%）影响。代码层面，该模块通过 `sys.path.insert` 直接引用主项目路径，存在包名不统一和缓存隔离问题，集成需做适配层。

---

## 一、输入文件审查

### 已读关键文件

| 文件 | 作用 | 结论 |
|------|------|------|
| `data_sources/eastmoney/holdings_full.py` | 通过 FundArchivesDatas.aspx?type=quarter 拉取全部持仓 | 可解析两种格式，返回含名称+占比+持股数+市值的 FundHolding |
| `backtest/run_backtest.py` | 多算法回测引擎，聚合 MAE/RMSE/MAX/over_th | 完整实现了 8 种算法的横向对比与 CSV 落盘 |
| `backtest/iteration_tracker.py` | 多算法横向对比 + 自动选优 | 薄封装层，直接调用 run_main() |
| `results/backtest_160211_2026-04-25_2026-07-15.csv` | 实际回测输出（50 行 × 30 列） | 含每日估算 NAV、误差和官方 NAV |
| `results/backtest_160211_2026-04-25_2026-07-16.csv` | 最新一次回测（50 行） | 增量扩展 |

---

## 二、关键发现

### 2.1 回测性能结果（MAE/RMSE）

从 CSV 数据中逐行提取 error_pp 字段并计算：

#### 全部 50 个交易日汇总

| 算法 | N | MAE (pp) | RMSE (pp) | MAX (pp) | >0.5pp |
|------|---|----------|-----------|----------|--------|
| v_active_top10 | 50 | 2.1477 | 2.6201 | 5.9281 | 50/50 |
| v_active_bench_csi300 | 50 | 1.1832 | 1.4177 | 3.5343 | 50/50 |
| v_active_bench_csi500 | 50 | 0.9982 | 1.2216 | 3.0096 | 50/50 |
| v_active_bench_csi1000 | 50 | 1.0410 | 1.2546 | 2.7982 | 50/50 |
| v_active_bench_cyb | 50 | 1.2917 | 1.5697 | 3.3820 | 50/50 |
| **v_active_top10_blend_csi1000_a0.3** | 50 | **0.7495** | **1.0396** | **3.0167** | 50/50 |
| v_active_alpha | 50 | 1.6901 | 2.0736 | 5.3781 | 50/50 |
| v_active_top10_resid_csi1000 | 50 | 0.8735 | 1.1053 | 2.8798 | 50/50 |
| v_active_top10_resid_cyb | 50 | 0.8744 | 1.1062 | 2.8819 | 50/50 |
| v_active_top10_resid_csi500 | 50 | 0.9380 | 1.1523 | 2.8335 | 50/50 |

#### 近期表现（2026-06-15 ~ 2026-07-15，24 个交易日）

| 算法 | N | MAE (pp) | RMSE (pp) | MAX (pp) | >0.5pp |
|------|---|----------|-----------|----------|--------|
| v_active_top10 | 24 | 3.2407 | 4.1456 | 10.1224 | 24/24 |
| v_active_bench_csi300 | 24 | 1.2508 | 1.5529 | 5.0843 | 24/24 |
| v_active_bench_csi500 | 24 | 0.9984 | 1.1845 | 2.8091 | 24/24 |
| v_active_bench_csi1000 | 24 | 1.0191 | 1.1383 | 2.7982 | 24/24 |
| v_active_bench_cyb | 24 | 1.3819 | 1.7734 | 4.4694 | 24/24 |
| **v_active_top10_blend_csi1000_a0.3** | 24 | **0.7019** | **0.9304** | **2.0576** | 24/24 |
| v_active_alpha | 24 | 1.7841 | 2.2143 | 6.4345 | 24/24 |
| v_active_top10_resid_csi1000 | 24 | 0.8252 | 1.0485 | 2.3593 | 24/24 |
| v_active_top10_resid_cyb | 24 | 0.8240 | 1.0471 | 2.3571 | 24/24 |
| v_active_top10_resid_csi500 | 24 | 0.8700 | 1.1220 | 2.5487 | 24/24 |

### 2.2 算法对比与选择机制

#### 8 种算法架构

```
┌─────────────────────────────────────────────────────────┐
│  v_active_top10                    → Top10 + 股票涨跌     │
│  v_active_bench_{csi300/csi500/   → 纯基准代理，无持仓    │
│     csi1000/cyb}                                              │
│  v_active_top10_blend              → Top10 + 基准混合     │
│      (主推, 可变 alpha)                                  │
│  v_active_alpha                    → Top10 + 残差 Alpha   │
│  v_active_top10_resid_{key}        → Top10 残差分解      │
└─────────────────────────────────────────────────────────┘
```

#### 聚合指标体系

`aggregate()` 函数计算：
- **MAE** — 平均绝对误差（pp），用于排序选优
- **RMSE** — 均方根误差（pp），惩罚大误差
- **MAX** — 最大单日日误差
- **over_th** — 超过 0.5pp 的天数/总天数

#### 自动选优逻辑

`iteration_tracker.py` 作为薄封装层调用 `run_backtest.main()`。选优标准是 **MAE 最低**。在当前测试集中：
- 全局最佳：`v_active_top10_blend_csi1000_a0.3`（MAE=0.7495pp）
- 次佳：`v_active_top10_resid_cy**b`（MAE=0.8744pp）
- 最差：`v_active_top10` 原始 top10 法（MAE=2.1477pp）

> ⚠️ 这里没有看到自动"选择"动作被持久化到配置或写入报告。tracker.py 只是调用了 run_main 打印排序结果。

### 2.3 holdings_full.py 数据解析能力

`fetch_full_holdings()` 通过东方财富季报 API 获取完整持仓：
- 返回字段：股票代码、名称、占比(%)、持股数、持仓市值
- 支持两种 JSON 结构变体（Dictionary 式和 List 式）
- 失败时 graceful return `None`，由 run_backtest.py 降级到 top10

---

## 三、集成兼容性风险

### 3.1 包命名不一致

| 组件 | 预期模块名 | 实际导入方式 |
|------|-----------|-------------|
| 主项目模型 | `core.models` | `from core.models import ...` |
| 主项目配置 | `core.config` | `from core import config` |
| Active 模块 | `fund_estimator_active.*` | 通过 `sys.path.insert` 指向 `ROOT = parent.parent` |

run_backtest.py 的核心问题是：
```python
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from data_sources.eastmoney.nav_history import fetch_history
from estimators.holdings_based import estimate_v_active_top10
```

这意味着 **它绕过了 Python 包结构**，直接用裸路径引用。如果主项目中这些模块在不同子目录下，路径将失效。

### 3.2 依赖链耦合

run_backtest.py 依赖以下主项目模块：
- `core.models` → FundHolding, StockPosition
- `core.config` → RESULTS_DIR, EAST_FUND_BASE
- `data_sources.eastmoney.nav_history` → fetch_history
- `data_sources.benchmark.get_benchmark` → benchmark_return, list_benchmarks
- `data_sources.sina.history` → fetch_kline, get_return_pct
- `estimators.holdings_based` → estimate_v_active_top10
- `estimators.benchmark_proxy` → estimate_v_active_bench
- `estimators.alpha_residual` → estimate_v_active_alpha
- `estimators.blend` → estimate_v_active_top10_blend, estimate_v_active_top10_resid

### 3.3 缓存隔离问题

| 缓存位置 | 用途 | 隔离风险 |
|---------|------|---------|
| `.cache/eastmoney/nav_history/160211.json` | 主项目 NAV | Active 模块共用同一缓存目录 |
| `.cache/sina/kline` | 股票 K 线 | Active 的 kline 缓存可能与主项目不同步 |

当前 active 模块没有独立 `.cache` 目录。如果两个模块并行运行，可能出现 **读写竞争** 或 **格式版本不兼容**。

### 3.4 sys.path 注入副作用

`sys.path.insert(0, ROOT)` 在多个脚本中重复执行，可能污染主项目或其他模块的导入路径。建议改用 `PYTHONPATH` 环境变量或 pyproject.toml 的 package discovery 配置。

---

## 四、风险提示与不确定性

| 风险 | 严重度 | 描述 |
|------|--------|------|
| 整体 MAE 仍偏高 | 🔴 | 即使最佳算法 MAE~0.75pp，50/50 天都超过 0.5pp 阈值 |
| 极端日表现差 | 🔴 | 7/10 单日 -4.95%，v_active_top10 误差达 5.9pp |
| v_active_top10_blend 并非稳定第一 | 🟡 | 在某些单日（如 5/20）其他算法更优 |
| 无交叉验证 | 🟡 | 只做了单一基金 160211 的回测，不能泛化到其他基金 |
| 缓存读写竞争 | 🟡 | 无锁机制，并行回测可能覆盖旧数据 |
| 自适应 alpha 未展示 | 🟢 | code 中有 `adaptive_alpha()` 但未在当前 run_backtest 输出中体现 |

---

## 五、建议

1. **集成路径改造**：在 fund_estimator_active 下创建 `pyproject.toml`，用 PEP 621 声明依赖，避免 `sys.path.insert`
2. **缓存隔离**：为 active 模块创建独立的 `.cache/fund_estimator_active/` 目录
3. **自动选优落地**：将 tracker.py 扩展为真正写入 "best_method" 的决策模块
4. **加入置信区间**：除 MAE 外增加中位数误差和分位数报告
5. **多基金回测**：至少增加 2-3 只不同类型的基金以验证泛化性
6. **极端行情分析**：单独报告跌幅 >3% 日的表现

---

## 六、行动项

| # | 行动 | 优先级 |
|---|------|--------|
| 1 | 修复 `fund_estimator_active` 的包路径引用，改为 proper package 结构 | P0 |
| 2 | 创建独立缓存目录 `.cache/fund_estimator_active/` | P0 |
| 3 | 扩展 iteration_tracker.py 实现自动选优并落盘 | P1 |
| 4 | 补充多基金回测结果 | P1 |
| 5 | 增加极端行情日单独分析面板 | P2 |
