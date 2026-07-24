"""估值器层。

本模块同时支持被动指数型和主动管理型基金估值。

被动/指数基金算法（5 种，见 holdings_based.py）：
- v_top10                纯前 10 大持仓还原
- v_index_full           全指数代理（含 cash_drag）
- v_index_full_no_cash   全指数代理（无 cash_drag）⭐ 主推
- v_index_blend          top10 + 指数混合
- v_residual_uncovered   top10 + uncovered 用 covered 均值代理

主动基金算法（8+ 种，见 active_*.py）：
- v_active_top10         纯持仓还原 top10
- v_active_bench_*       纯基准指数代理（5个候选）
- v_active_top10_blend   top10 + α×长尾×bench ⭐ 主推
- v_active_top10_resid_* top10 + 残差完全跟随某 benchmark
- v_active_alpha         top10 + 长尾×(bench + 历史alpha)
"""

from .holdings_based import (
    estimate,
    METHODS,
    METHOD_LABELS,
    DEFAULT_METHOD,
)

# 主动基金估值入口
from .active import (
    get_estimator as get_active_estimator,
    list_methods as list_active_methods,
    ALL_METHODS as active_methods,
)

# 主动基金算法直接导出（兼容外部调用）
from .active_holdings import estimate_v_active_top10
from .active_benchmark import estimate_v_active_bench
from .active_blend import estimate_v_active_top10_blend, estimate_v_active_top10_resid
from .active_alpha import estimate_v_active_alpha

__all__ = [
    # 被动/指数
    "estimate",
    "METHODS",
    "METHOD_LABELS",
    "DEFAULT_METHOD",
    # 主动基金入口
    "get_active_estimator",
    "list_active_methods",
    "active_methods",
    # 主动基金算法
    "estimate_v_active_top10",
    "estimate_v_active_bench",
    "estimate_v_active_top10_blend",
    "estimate_v_active_top10_resid",
    "estimate_v_active_alpha",
    "active_module",
]

# 兼容：同时导出 active 子模块
from . import active as active_module
