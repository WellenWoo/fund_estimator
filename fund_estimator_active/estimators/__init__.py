"""estimators 包 — 主动基金估值算法集合。"""
from __future__ import annotations
from typing import Callable, Optional

from .holdings_based import estimate_v_active_top10
from .benchmark_proxy import estimate_v_active_bench
from .blend import estimate_v_active_top10_blend, estimate_v_active_top10_resid
from .alpha_residual import estimate_v_active_alpha

ESTIMATOR_MAP = {
    "v_active_top10": estimate_v_active_top10,
    "v_active_top10_blend": estimate_v_active_top10_blend,
    "v_active_alpha": estimate_v_active_alpha,
}


def get_estimator(method: str) -> Callable:
    """根据方法名返回估值函数。
    
    Args:
        method: 算法名称
        
    Returns:
        对应的估值函数
    """
    if method in ESTIMATOR_MAP:
        return ESTIMATOR_MAP[method]
    if method.startswith("v_active_bench_"):
        return estimate_v_active_bench
    if method.startswith("v_active_top10_resid_"):
        return estimate_v_active_top10_resid
    raise ValueError(f"Unknown method: {method}")


def list_methods() -> list[str]:
    """返回所有可用算法名称列表。"""
    methods = list(ESTIMATOR_MAP.keys())
    methods.extend([
        "v_active_bench_csi300",
        "v_active_bench_csi500",
        "v_active_bench_csi1000",
        "v_active_bench_cyb",
        "v_active_top10_resid_csi1000",
        "v_active_top10_resid_csi500",
        "v_active_top10_resid_cyb",
    ])
    return methods
