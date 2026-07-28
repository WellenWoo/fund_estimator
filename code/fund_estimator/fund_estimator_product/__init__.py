"""商品/商品期货基金估值模块。

项目目标
--------
为「商品 / 商品期货」类 LOF/ETF（如 161226 国投瑞银白银期货(LOF)A）提供
盘中实时估值与历史回测能力。

与 ``fund_estimator.estimators`` 的差异
------------------------------------
- 被动指数 LOF（160223 / 160615）跟踪的是**指数**，可直接拿指数日线
  当作组合价值的无偏估计（ITERATIONS §3 验证：MAE 0.11pp）。
- 商品 / 商品期货 LOF **没有可复制的指数**。它的净值取决于
  上期所/上金所/大商所某个具体品种期货的日内走势，以及基金的
  期货仓位、保证金占用、移仓损益、申赎现金流等。
- 因此本模块走「**品种期货价格代理** + 仓位/费率校正」路线，
  复用 ``fund_estimator`` 的 NAVEstimate / NAVComparison 数据模型，
  但算法实现独立。

核心算法
--------
+------------------------------+-----------------------------------------------+
| v_commodity_proxy            | T-1 涨跌% 当 T 涨跌%（动量代理）               |
+------------------------------+-----------------------------------------------+
| v_commodity_random_walk ⭐    | T 日涨跌% = 0（无偏随机游走基线）              |
+------------------------------+-----------------------------------------------+
| v_commodity_blend            | 动量 30% + 随机游走 70%（保守混合）            |
+------------------------------+-----------------------------------------------+
| v_commodity_decay            | 动量 50%，按 1/2 衰减（短期反转）              |
+------------------------------+-----------------------------------------------+
| v_commodity_futures_realtime | 直接用 SHFE 期货实时价 T-1 收盘 → T 现价       |
+------------------------------+-----------------------------------------------+

注：所有算法对单日 NAV 的核心更新公式都遵循 README §4： ::

    估算 NAV(T) = T-1 NAV × (1 + 估算涨跌%)

设计原则
--------
1. 复用 ``fund_estimator`` 已有数据模型（NAVEstimate / NAVComparison）
   与缓存（``CsvCache``），保证上层 GUI / Agent 集成成本最低。
2. 不引入任何第三方依赖（仅标准库 + ``fund_estimator.data_sources``）。
3. 算法与底层商品一一解耦：通过 ``COMMODITY_MAP`` 显式声明
   "哪只 LOF 跟踪哪个品种"，便于扩展。
"""

from __future__ import annotations

from .commodity_map import (
    CommodityInfo,
    COMMODITY_MAP,
    get_commodity_for_fund,
    list_supported_funds,
)
from .estimators import (
    DEFAULT_METHOD,
    METHODS,
    METHOD_LABELS,
    estimate,
)
from .realtime import estimate_commodity_realtime
from .backtest import (
    BacktestResult,
    CommonInputs,
    backtest_range,
    backtest_all_methods,
    load_common_inputs,
    estimate_for_day,
)

__all__ = [
    "CommodityInfo",
    "COMMODITY_MAP",
    "get_commodity_for_fund",
    "list_supported_funds",
    "DEFAULT_METHOD",
    "METHODS",
    "METHOD_LABELS",
    "estimate",
    "estimate_commodity_realtime",
    "BacktestResult",
    "CommonInputs",
    "backtest_range",
    "backtest_all_methods",
    "load_common_inputs",
    "estimate_for_day",
]

__version__ = "0.1.0"
