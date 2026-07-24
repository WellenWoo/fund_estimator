"""主动型基金估值算法集合。

提供 8+ 种算法，适用于非被动指数基金（is_passive=false）。
算法体系与 fund_estimator.estimators.holdings_based 互补：

┌──────────────────────┬───────────────────────────────────────────────┐
│ 算法                  │ 说明                                         │
├──────────────────────┼───────────────────────────────────────────────┤
│ v_active_top10       │ 纯前10大持仓还原（无长尾处理）                    │
│ v_active_bench_csi300│ 沪深300 纯基准代理                               │
│ v_active_bench_csi500│ 中证500 纯基准代理                               │
│ v_active_bench_csi1000│ 中证1000 纯基准代理                              │
│ v_active_bench_cyb   │ 创业板指 纯基准代理                               │
│ v_active_top10_blend │ top10 真实 + α×长尾×bench（主推）                 │
│ v_active_alpha       │ top10 + 长尾×(bench + 历史alpha)                  │
│ v_active_top10_resid_*│ top10 + 长尾完全跟随某bench                      │
└──────────────────────┴───────────────────────────────────────────────┘
"""

from __future__ import annotations

from typing import Optional, Callable

from .active_holdings import estimate_v_active_top10
from .active_benchmark import estimate_v_active_bench
from .active_blend import estimate_v_active_top10_blend, estimate_v_active_top10_resid
from .active_alpha import estimate_v_active_alpha

ESTIMATOR_MAP: dict[str, Callable] = {
    "v_active_top10": estimate_v_active_top10,
    "v_active_top10_blend": estimate_v_active_top10_blend,
    "v_active_alpha": estimate_v_active_alpha,
}

ALL_METHODS = [
    "v_active_top10",
    "v_active_top10_blend",
    "v_active_alpha",
    "v_active_bench_csi300",
    "v_active_bench_csi500",
    "v_active_bench_csi1000",
    "v_active_bench_cyb",
    "v_active_top10_resid_csi300",
    "v_active_top10_resid_csi500",
    "v_active_top10_resid_csi1000",
    "v_active_top10_resid_cyb",
]

# 兼容别名
list_methods = list_active_methods = lambda: ALL_METHODS


def get_estimator(method: str) -> Callable:
    """根据方法名返回估值函数。"""
    if method in ESTIMATOR_MAP:
        return ESTIMATOR_MAP[method]
    if method.startswith("v_active_bench_"):
        return estimate_v_active_bench
    if method.startswith("v_active_top10_resid_"):
        return estimate_v_active_top10_resid
    raise ValueError(f"Unknown active method: {method}. choices={ALL_METHODS}")


def list_methods() -> list[str]:
    """返回所有可用算法名称列表。"""
    return ALL_METHODS
