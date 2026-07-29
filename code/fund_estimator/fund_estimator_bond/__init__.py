"""债券型基金实时估值模块 (Fund Estimator — Bond)

项目目标
--------
为「纯债 / 一级债基 / 二级债基」等债券型 LOF/ETF（如 164703 汇添富纯债(LOF)A）
提供盘中实时估值 + 历史回测能力。

与 ``fund_estimator`` 其他子模块的差异
---------------------------------------
- 被动指数 LOF（160223 / 160615）跟踪的是 A 股指数，估值核心 = 指数日线 = 组合价值无偏估计（ITERATIONS §3 验证 MAE 0.11pp）。
- 主动股票基金（161005 等）有可获取的 top10 股票持仓 + 股票指数作长尾代理（v_active_top10_blend，MAE ~0.75pp）。
- 主动/被动型债券基金（164703 等）**无公开复制标的**：
  - 底层是利率债 + 信用债 + 少量股票（<5%），不是股票、不是商品、不是 A 股指数；
  - 季报披露的「前 5 大持仓」是债券代码（利率债 / 信用债），占比 30-50%；
  - 净值日波动小（实测 ±0.05pp），对算法绝对误差极敏感；
  - **正确代理 = 公开市场债券指数**（上证公司债 / 沪深企业债 / 上证国债等）。

核心算法
--------
+-----------------+----------------------------------------------------+
| v_bond_csi_corp | 沪深企业债指数 (sh000061) 直接代理（主推）            |
|                 | 波动与纯债基实际日收益同量级，回归显示 beta≈1          |
+-----------------+----------------------------------------------------+
| v_bond_sse_gov  | 上证国债指数 (sh000012) 代理（保守）                  |
|                 | 久期/利率敏感度更高，适合利率债占比 >70% 的债基       |
+-----------------+----------------------------------------------------+
| v_bond_t1_persist | T 日涨跌% = T-1 涨跌%（动量 / 持久性代理）          |
|                 | 仿 fund_estimator_product.v_commodity_proxy         |
+-----------------+----------------------------------------------------+
| v_bond_random_walk | T 日涨跌% = 0（无偏随机游走基线）                  |
|                 | 仿 fund_estimator_product.v_commodity_random_walk    |
+-----------------+----------------------------------------------------+
| v_bond_blend    | 0.3 × T-1 + 0.7 × 0（保守动量混合）                 |
|                 | 仿 fund_estimator_product.v_commodity_blend         |
+-----------------+----------------------------------------------------+

设计原则
--------
1. 复用 ``fund_estimator`` 既有数据模型 (NAVEstimate / NAVComparison) 与缓存层 (CsvCache)，
   保证上层 GUI / Agent 集成成本最低。
2. 不引入任何第三方依赖（仅标准库 + ``fund_estimator.data_sources``）。
3. 基金与底层代理通过 ``BOND_MAP`` 显式声明，新增债基时只追加一行。
"""

from __future__ import annotations

from .bond_map import (
    BondInfo,
    BOND_MAP,
    get_bond_info_for_fund,
    list_supported_funds,
)
from .estimators import (
    DEFAULT_METHOD,
    METHODS,
    METHOD_LABELS,
    estimate,
)
from .backtest import (
    BacktestResult,
    CommonInputs,
    backtest_range,
    backtest_all_methods,
    load_common_inputs,
    estimate_for_day,
)
from .realtime import estimate_bond_realtime

__all__ = [
    "BondInfo",
    "BOND_MAP",
    "get_bond_info_for_fund",
    "list_supported_funds",
    "DEFAULT_METHOD",
    "METHODS",
    "METHOD_LABELS",
    "estimate",
    "estimate_bond_realtime",
    "BacktestResult",
    "CommonInputs",
    "backtest_range",
    "backtest_all_methods",
    "load_common_inputs",
    "estimate_for_day",
]

__version__ = "0.1.0"
