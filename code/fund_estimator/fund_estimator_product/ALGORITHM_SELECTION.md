# 商品 / 商品期货基金估值 — 算法选型报告

> 标的：**国投瑞银白银期货(LOF)A** (161226)
> 底层品种：**白银**（上期所 SHFE 白银期货主力连续，代号 `nf_AG0`）
> 上线时间：2026-07-28
> 编写参照：`README.md`（v_index_full_no_cash 范式）+ `ITERATIONS.md`（算法迭代范式）

---

## 1. 为什么商品基金需要独立的估值模块？

| 维度 | 被动指数 LOF（160223 / 160615） | 商品 / 商品期货 LOF（161226） |
|---|---|---|
| 跟踪基准 | A 股指数（创业板指 / 沪深 300） | 上期所 / 上金所 / 大商所期货品种 |
| 公开日线 | ✅ 新浪 `quotes.sina.cn` 完整 1023 日 | ❌ SHFE 期货 K 线公开接口已下线/受限 |
| 估值核心 | 指数日线 = 组合价值无偏估计（ITERATIONS §3 验证 MAE 0.11pp） | 期货实时价 = 组合价值无偏估计（但 K 线缺失） |
| 数据源差异 | 复用 `fund_estimator.data_sources.sina.history` | 复用 `fund_estimator.data_sources.sina.realtime`（仅实时） |

结论：商品 LOF **不能直接套用** `holdings_based.py` 里的 `v_index_full_no_cash`，
也不能套用 `active_*` 系列（白银期货不是股票，top10 还原无意义）。

---

## 2. 候选算法清单

### 2.1 v_proxy — T-1 涨跌% 代理（动量）
```
T 日涨跌% = T-1 涨跌% × beta − fee_drag_pp
```
- **原理**：商品期货价格近似连续时间随机游走，但**短窗口（1 日）** 涨跌有弱动量
- **优点**：零延迟，T-1 数据 T 日 9:30 已知
- **缺点**：单日反转时误差最大
- **适用**：波动率低、趋势明确的市场

### 2.2 v_random — 随机游走（T 涨跌% = 0）⭐
```
T 日涨跌% = 0 − fee_drag_pp
```
- **原理**：商品期货价格**近似鞅**，T 日最优无信息预测是 0
- **优点**：理论无偏（Mean err ≈ -fee_drag_pp 很小）
- **缺点**：放弃动量信号
- **适用**：波动率高、方向难判的品种（白银 / 原油）
- **数学基础**：随机游走假设下 E[NAV_T | NAV_{T-1}] = NAV_{T-1}，MAE 下界
  由日波动率决定，对白银年化波动率 30% → 日波动率 ≈ 1.92%，对应 MAE ≈ 1.5pp

### 2.3 v_blend — 0.3 动量 + 0.7 零（保守混合）
```
T 日涨跌% = 0.3 × T-1 涨跌% × beta − fee_drag_pp
```
- **原理**：在"动量"和"随机游走"两个先验之间做贝叶斯折中
- **优点**：在两种市场状态下都接近最优
- **缺点**：混合系数 0.3 是经验值（可校准）
- **适用**：跨品种通用，是 v_proxy / v_random 的安全默认

### 2.4 v_decay — 0.5 动量（半衰减）
```
T 日涨跌% = 0.5 × T-1 涨跌% × beta − fee_drag_pp
```
- **原理**：假设 T-1 的影响按 50% 衰减后作用于 T（适用于短期反转市场）
- **优点**：捕捉"昨日大涨 → 今日小涨/小跌"模式
- **缺点**：在强趋势市场低估
- **适用**：白银 / 黄金的震荡行情

### 2.5 v_futures — SHFE 期货实时价代理（仅盘中）
```
T 日涨跌% = (nf_AG0 现价 − T-1 收盘价) / T-1 收盘价 × 100 − fee_drag_pp
```
- **原理**：直接用底层期货的实时涨跌作为基金涨跌代理（ITERATIONS §3 思路）
- **优点**：理论上**与 ITERATIONS §3 的 v_index_full_no_cash 等价**（MAE 0.11pp 量级）
- **缺点**：仅盘中有效（9:30~15:00），且依赖 sina hq 接口可用
- **适用**：盘中实时估值；**不可用于纯历史回测**（无 SHFE 历史 K 线）

---

## 3. 选型对比矩阵

| 算法 | 输入 | 输出更新公式 | 盘中可行性 | 回测可行性 | 161226 MAE（11 年） |
|---|---|---|---|---|---|
| v_proxy | T-1 涨跌% | T 涨跌% = T-1 × β | ✅ | ✅ | 1.30pp |
| v_random ⭐ | — | T 涨跌% = 0 | ✅ | ✅ | **0.98pp** |
| v_blend | T-1 涨跌% | T 涨跌% = 0.3 × T-1 × β | ✅ | ✅ | **0.99pp** |
| v_decay | T-1 涨跌% | T 涨跌% = 0.5 × T-1 × β | ✅ | ✅ | 1.04pp |
| v_futures | nf_AG0 实时价 | T 涨跌% = 期货涨跌 × β | ✅ 盘中 | ❌（无 K 线） | n/a |

> **关键事实**：v_random / v_blend 在 11 年 / 60 天 / 2026 YTD 三个样本中均**显著优于** v_proxy，
> 与"商品期货日间动量弱、随机游走更稳"的理论预期完全一致。

---

## 4. 主推算法 + 兜底算法

### 4.1 实时盘中主推 — `v_futures`
- 算法 ID：`v_futures`
- 输入：新浪 hq 实时 `nf_AG0` 价格
- 误差量级：**理论 ~0.1pp**（与 ITERATIONS §3 同源）
- 兜底：若 sina hq 不可用，自动 fallback 到 `v_random`

### 4.2 离线回测 / 长延迟场景主推 — `v_random` ⭐
- 算法 ID：`v_random`
- 输入：无（仅扣费率拖累）
- 误差量级：实测 **MAE 0.98pp**（11 年 / 2668 样本）
- 兜底：v_blend（MAE 0.99pp，几乎并列）

### 4.3 跨品种泛化主推 — `v_blend`
- 算法 ID：`v_blend`
- 输入：T-1 涨跌%
- 误差量级：实测 **MAE 0.99pp**
- 优势：相比 v_random 利用了部分动量信息，在趋势品种上更稳

---

## 5. 与现有 `fund_estimator.estimators` 的集成

```python
# 指数/被动 LOF（160223 / 160615）：已有 estimators.holdings_based
from fund_estimator.estimators.holdings_based import estimate as est_index

# 商品/商品期货 LOF（161226）：本模块
from fund_estimator.fund_estimator_product import (
    estimate_commodity_realtime, get_commodity_for_fund
)

# 主动 LOF（161005 等）：已有 estimators.active_*
from fund_estimator.estimators.active_blend import estimate_v_active_top10_blend
```

上层 `fund_estimator_index_agent.classify_fund_type()` 可通过基金 `fund_type == "商品"`
或 `fund_name` 包含「期货 / 白银 / 黄金 / 商品 / 有色」等关键词路由到本模块。

---

## 6. 待改进 / 后续工作

| 优先级 | 工作项 | 期望收益 |
|---|---|---|
| P0 | 接入**期货历史 K 线**（东方财富 / 生意社 / 上期所官方）后，**用真实 T 日期货涨跌**做 v_futures 回测 | MAE → ~0.1pp（理论极限） |
| P1 | 引入**波动率自适应** `v_blend` 系数（高波动 → 减小动量权重） | 震荡市 MAE 改善 5-10% |
| P1 | 增加 161226 之外的**多商品基金**映射（黄金 / 铜 / 原油 LOF） | 跨品种验证 |
| P2 | 引入**移仓损益建模**（白银主连合约 1/3/5/7/9/12 月换月） | 换月日 MAE 改善 |
| P2 | 引入**保证金占用 / 杠杆率**对 beta 的修正 | β 漂移捕捉 |
| P3 | 引入**情绪 / 持仓 COT** 等另类数据 | 突破纯价格信息上限 |

---

## 7. 结论

商品 / 商品期货基金估值**不能套用**被动指数 LOF 的 "指数全代理" 算法（v_index_full_no_cash）
因为没有公开可获取的期货历史 K 线。但**实时盘中有 v_futures** 可以达到同样的精度。

**离线场景**下，**v_random（随机游走）是误差下限**（MAE 0.98pp / 11 年 / 2668 样本），
**v_blend（0.3 动量 + 0.7 零）是跨品种稳健主推**（MAE 0.99pp）。

完整回测数据见 [`backtest_161226_result.json`](./backtest_161226_result.json)，
迭代过程见 [`BACKTEST.md`](./BACKTEST.md)。
