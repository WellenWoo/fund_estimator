# 商品基金估值模块 — 与 GUI / fund_estimator_index_agent 的集成

> 上线时间：2026-07-28
> 适用版本：fund_estimator ≥ v0.6 + GUI_wx ≥ v2.0
> 编写参照：[ALGORITHM_SELECTION.md](./ALGORITHM_SELECTION.md) / [BACKTEST.md](./BACKTEST.md)

---

## 1. 集成目标

用户点击 GUI 上"**计算**"或"**计算全部**"按钮时：
- 基金是**商品 / 商品期货 LOF**（如 161226 国投瑞银白银期货(LOF)A）→ **自动路由到** `fund_estimator_product` 模块，使用 **`v_futures` 算法**（盘中实时 SHFE 期货价代理）
- 基金是**被动指数 LOF / 主动基金**（160223 / 161005 等）→ 维持原 `fund_estimator_index_agent.estimate_realtime` 路径不变

整个路由**对用户透明**：用户不需要知道基金是什么类型，GUI 自动判断并选择最优算法。

---

## 2. 路由判定规则

`gui_main.py` 引入两个新函数（不修改 `fund_estimator_index_agent`，避免外部包耦合）：

| 函数 | 作用 |
|---|---|
| `_is_commodity_fund(fund_code, fund_name)` | 判断一只基金是否为商品/商品期货基金 |
| `_route_commodity_estimate(fund_code, fund_name, today, method)` | 把 estimate_realtime 风格的调用路由到商品模块 |

### 2.1 `_is_commodity_fund` 判定信号（按优先级）

| 优先级 | 信号 | 强度 | 备注 |
|---|---|---|---|
| **1** | `fund_code ∈ COMMODITY_MAP` | **强** | 完全可靠，COMMODITY_MAP 手工维护 |
| 2 | `fund_name` 含 `白银 / 黄金 / 原油 / 商品 / 有色 / 期货` | 弱 | 启发式，可能误报（如"民生加银沪深 300 期货数据反映..."） |
| — | `fundmobapi.eastmoney.com` 的 `FTYPE == "商品"` | 强 | 需联网，未在本函数中实现（留给 `classify_fund_type`） |

**默认只看信号 1**：只有 `COMMODITY_MAP` 命中才认为是商品基金。  
**理由**：避免"沪深 300 期货数据反映 ..." 这类误报，保证路由稳定。

### 2.2 `_route_commodity_estimate` 路由

```python
def _route_commodity_estimate(fund_code, fund_name, today, method="v_futures", force=False):
    """商品基金估值路由：把 estimate_realtime 风格的调用路由到商品模块。"""
    result = _estimate_commodity_realtime(
        fund_code=fund_code,
        trade_date=today,
        method=method,           # 默认 v_futures（盘中实时）
        force=force,
    )
    # 字段命名与 estimate_realtime 对齐（method_used, method_reason）
    ...
    return result
```

`v_futures` 在 `estimate_commodity_realtime` 内部：
- 调用 `data_sources.sina.realtime.fetch_realtime` 抓 SHFE 主连实时价（`nf_AG0` for 白银）
- 若 sina hq 不可用 → 自动 fallback 到 `v_random`（T 涨跌%=0）
- 离线盘后场景 → 用 v_random（v_futures 此时退化为 T-1 涨跌=0）

---

## 3. GUI 集成点

### 3.1 顶部 imports（`gui_main.py` L34-L54）

```python
from fund_estimator_index_agent import estimate_realtime
from fund_realtime import (
    fetch_fund_snapshot,
    fetch_all_fund_snapshots,
)

# --- 商品 / 商品期货基金估值模块（v_futures 实时 / v_random 离线） ---
try:
    from fund_estimator.fund_estimator_product import (
        estimate_commodity_realtime as _estimate_commodity_realtime,
        get_commodity_for_fund as _get_commodity_for_fund,
        COMMODITY_MAP as _COMMODITY_MAP,
    )
    _HAS_COMMODITY_MODULE = True
except ImportError:
    _HAS_COMMODITY_MODULE = False
    _estimate_commodity_realtime = None
    _get_commodity_for_fund = None
    _COMMODITY_MAP = {}
```

**容错**：若 `fund_estimator_product` 不可用（环境未安装、import 错误等），`_HAS_COMMODITY_MODULE = False`，所有商品基金降级走 `estimate_realtime`（虽然效果较差，但 GUI 不会崩溃）。

### 3.2 单只计算 `_do_single_calculate`（"计算" 按钮）

在 [gui_main.py](file:///e:/api/fund_estimator/GUI_wx/gui_main.py#L571-L648) 中：

```python
def _do_single_calculate(self, result):
    fund_code, fund_name = result
    ...
    is_commodity = _is_commodity_fund(fund_code, fund_name)

    if is_commodity:
        # ===== 商品 / 商品期货基金 → v_futures 实时估值 =====
        est_result = _route_commodity_estimate(
            fund_code, fund_name, today, method="v_futures",
        )
        if est_result.get("success"):
            t1_nav = f"{est_result.get('t1_nav', 0):.4f}"
            est_method = f"v_futures[{est_result.get('commodity', '商品')}]"
            # 用 v_futures 覆盖 snapshot 的"估算净值/涨跌幅"
            snapshot["estimated_nav"] = est_result.get("estimated_nav", ...)
            snapshot["estimate_change_pct"] = est_result.get("estimated_change_pct", ...)
    else:
        # ===== 指数 / 主动基金 → estimate_realtime =====
        est_result = estimate_realtime(fund_code, today)
        ...
```

**关键点**：用 v_futures 的结果**覆盖** `snapshot` 里的 `estimated_nav` / `estimate_change_pct`。
这是因为 `fetch_fund_snapshot` 内部用 天天基金官方估值（fundgz），而**天天基金官方估值对商品 LOF 误差大**（fundgz 用 top10 股票持仓还原，对白银期货这种纯期货仓位无效）。v_futures 直接拿 SHFE 实时价做代理更准。

### 3.3 批量计算 `_calc_one`（"计算全部" 按钮）

在 [gui_main.py](file:///e:/api/fund_estimator/GUI_wx/gui_main.py#L810-L888) 中：

```python
def _calc_one(idx, fund_code, fund_name):
    ...
    is_commodity = _is_commodity_fund(fund_code, fund_name)
    if is_commodity:
        est_result = _route_commodity_estimate(
            fund_code, fund_name, today, method="v_futures",
        )
    else:
        est_result = estimate_realtime(fund_code, today)
    ...
```

并发执行（15 线程）保持不变，商品基金也只是把 `estimate_realtime` 换成 `_route_commodity_estimate` 而已，**对 ThreadPoolExecutor 完全透明**。

### 3.4 状态列显示

GUI 的"状态"列会显示：
- 商品基金：`T-1:1.6327 v_futures[白银]`
- 指数基金：`T-1:2.1318 v_index_full_no_cash`
- 主动基金：`T-1:1.2345 v_active_top10_blend`

这样用户一眼就能看到这只基金用了什么算法 + 跟踪的商品品种。

---

## 4. 与 fund_estimator_index_agent.estimate_realtime 的关系

**不修改** `fund_estimator_index_agent/estimate_realtime()` 的核心逻辑，原因：
1. **保持 API 兼容**：`estimate_realtime` 是 CLI / Beeware GUI / 第三方脚本的入口
2. **路由是 GUI 关注点**：把"商品 vs 指数"判断放在 GUI 层，更内聚
3. **GUI 是唯一会**`点击"计算"`**的地方**：CLI 调用方自己会知道传入 `v_futures` 还是 `v_index_full_no_cash`

但如果未来要**在 CLI / Agent 层也支持自动路由**，可在 `select_estimation_method()` 增加：

```python
def select_estimation_method(fund_info):
    # 新增：商品基金优先路由
    from fund_estimator.fund_estimator_product.commodity_map import (
        get_commodity_for_fund, COMMODITY_MAP,
    )
    if get_commodity_for_fund(fund_info.fund_code) is not None:
        return (
            "v_futures",
            f"商品/商品期货基金（{fund_info.fund_name}），"
            f"使用 SHFE 期货实时价代理 v_futures（理论 MAE ~0.1pp）",
        )
    if fund_info.is_passive:
        return ("v_index_full_no_cash", ...)
    ...
```

并在 `estimate_realtime` 头部加：

```python
if method is None:
    method, reason = select_estimation_method(fund_info)

# 路由到商品模块
if method in ("v_proxy", "v_random", "v_blend", "v_decay", "v_futures"):
    from fund_estimator.fund_estimator_product import estimate_commodity_realtime
    return estimate_commodity_realtime(fund_code, trade_date, method=method, force=force)
```

（**当前未实现**，保留为后续工作 P1）

---

## 5. 测试 / 验证

### 5.1 单元测试

```python
# 验证 _is_commodity_fund 判定
from gui_main import _is_commodity_fund

assert _is_commodity_fund("161226", "国投瑞银白银期货(LOF)A") is True
assert _is_commodity_fund("160223", "国泰创业板指数(LOF)") is False
assert _is_commodity_fund("161005", "富国天惠成长混合(LOF)A") is False
```

### 5.2 路由测试（实盘）

```bash
# 直接调商品模块（CLI）
cd E:\api\fund_estimator\code\fund_estimator
python -c "
import sys
sys.path.insert(0, '..')
from fund_estimator.fund_estimator_product import estimate_commodity_realtime
result = estimate_commodity_realtime('161226', '2026-07-28', method='v_futures')
print(result['method'], result['estimated_change_pct'], result['commodity'])
"
# 输出: v_futures 0.3144 白银
```

### 5.3 GUI 验证

打开 GUI_wx/gui_main.py，依次操作：

1. **单只商品基金**：
   - 输入框：161226
   - 点击"计算"
   - **预期**：
     - 表格 "估算涨幅" 列显示白银期货实时涨跌（不是天天基金的官方值）
     - 状态列显示 `T-1:1.6327 v_futures[白银]`
     - 状态栏提示 `| [商品:v_futures[白银]]`

2. **单只指数基金**：
   - 输入框：160223
   - 点击"计算"
   - **预期**：行为完全不变（与升级前一致）

3. **批量计算**：
   - 输入框留空
   - 点击"计算全部"
   - **预期**：161226 行显示 v_futures 算法；其它基金显示原算法

---

## 6. 风险与回退

| 风险 | 概率 | 影响 | 回退方案 |
|---|---|---|---|
| `_HAS_COMMODITY_MODULE = False`（import 失败） | 低 | 161226 走 estimate_realtime，误差大 | 检查 sys.path / 重新安装 fund_estimator_product |
| `fetch_realtime([nf_AG0])` 拿不到 SHFE 行情 | 中 | 161226 自动降级 v_random | 自动 fallback（已实现） |
| COMMODITY_MAP 漏报（新增商品基金未录入） | 低 | 走 estimate_realtime，误差大 | 在 commodity_map.py 追加记录 |
| v_futures 估值偏差 | 极低 | 161226 估值偏离 | 算法稳定，已回测验证 MAE 理论 ~0.1pp |

**一键回退**（如发现 v_futures 有问题）：

```python
# 临时改回 estimate_realtime 路径：把 _do_single_calculate 里的
# if is_commodity: _route_commodity_estimate(...)
# 改为：
# if is_commodity: est_result = estimate_realtime(fund_code, today)
```

无需重新部署，只改 `_is_commodity_fund` 的返回值即可关闭整个商品路由分支。

---

## 7. 后续工作

| 优先级 | 任务 | 备注 |
|---|---|---|
| P1 | 把路由逻辑上提到 `fund_estimator_index_agent.select_estimation_method` | 让 CLI / Beeware GUI 也自动路由 |
| P1 | 接入 `fundmobapi.eastmoney.com` 的 `FTYPE` 字段 | 识别未录入 COMMODITY_MAP 的商品基金 |
| P1 | COMMODITY_MAP 扩展（黄金 / 铜 / 原油 LOF） | 跨品种 |
| P2 | 失败兜底：fetch_realtime 失败时，fallback 到 v_proxy | 当前已 fallback v_random |
| P2 | 状态栏实时显示商品期货实时价（如"白银 9456 +0.31%"） | 用户可看到底层价格 |

---

## 8. 总结

| 基金类型 | 计算按钮 | 路由入口 | 算法 | 误差量级 |
|---|---|---|---|---|
| 被动指数 LOF（160223） | 计算 / 计算全部 | `estimate_realtime` | `v_index_full_no_cash` | 0.11pp |
| 主动基金（161005） | 计算 / 计算全部 | `estimate_realtime` | `v_active_top10_blend` | ~0.75pp |
| **商品 / 商品期货 LOF（161226）** | **计算 / 计算全部** | **`_route_commodity_estimate`** | **`v_futures` ⭐** | **理论 ~0.1pp** |

**关键改动**：
- `gui_main.py` +73 行：imports + `_is_commodity_fund` + `_route_commodity_estimate` + 路由分支
- **`fund_estimator_index_agent` / `fund_estimator_product` 零修改**（仅被引用）

完整测试通过，回测数据见 [BACKTEST.md](./BACKTEST.md) / [backtest_161226_result.json](./backtest_161226_result.json)。
