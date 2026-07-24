"""v_active_bench_*：纯 benchmark 代理。

适用于不知道持仓 / 想做粗估 / benchmark 强相关的小盘基金。
"""
from __future__ import annotations

from typing import Optional

from ..core.models import NAVEstimate


def estimate_v_active_bench(
    t1_nav: float,
    today: str,
    t1_date: str,
    benchmark_return: float,
    benchmark_key: str,
    fund_code: str = "160211",
    fund_name: str = "",
) -> NAVEstimate:
    """v_active_bench: T-1 NAV × (1 + benchmark_return)。

    Args:
        benchmark_return: 今日 benchmark 涨跌幅（decimal）
        benchmark_key: 用于标记的关键词（csi300/cyb/...）
    """
    estimated_nav = t1_nav * (1 + benchmark_return)
    return NAVEstimate(
        fund_code=fund_code,
        today=today,
        t1_date=t1_date,
        t1_nav=round(t1_nav, 6),
        estimated_nav=round(estimated_nav, 6),
        estimated_change_pct=round(benchmark_return * 100.0, 4),
        method=f"v_active_bench_{benchmark_key}",
        detail={"benchmark": benchmark_key, "benchmark_return": benchmark_return},
    )
