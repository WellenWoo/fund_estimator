"""估值器层。

holdings_based.py 实现 5 种算法：
- v_top10                纯前 10 大持仓还原
- v_index_full           全指数代理（含 cash_drag）
- v_index_full_no_cash   全指数代理（无 cash_drag）⭐ 主推
- v_index_blend          top10 + 指数混合
- v_residual_uncovered   top10 + uncovered 用 covered 均值代理
"""

from .holdings_based import (
    estimate,
    METHODS,
    METHOD_LABELS,
    DEFAULT_METHOD,
)

__all__ = [
    "estimate",
    "METHODS",
    "METHOD_LABELS",
    "DEFAULT_METHOD",
]
