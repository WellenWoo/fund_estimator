"""estimators/benchmark_proxy.py — v_active_bench_*

纯 benchmark 代理: 假设基金走势 = 基准指数。
适用于不知道持仓 / 想做粗估 / benchmark 强相关的小盘基金。
"""
from __future__ import annotations
from datetime import date as Date
from typing import Optional

from core.models import NAVEstimate


def estimate_v_active_bench(t1_nav: float, today: Date, t1_date: Date,
                            benchmark_return: float, benchmark_key: str,
                            fund_code: str = "160211",
                            fund_name: str = "国泰中小盘成长混合(LOF)") -> NAVEstimate:
    """v_active_bench: T-1 NAV × (1 + benchmark_return).

    Args:
        benchmark_return:  今日 benchmark 涨跌幅 (decimal)
        benchmark_key:     用于日志/标记 (csi1000 / cyb / csi300 / ...)
    """
    estimated_nav = t1_nav * (1 + benchmark_return)
    return NAVEstimate(
        fund_code=fund_code, fund_name=fund_name,
        today=today, t1_date=t1_date, t1_nav=t1_nav,
        estimated_nav=estimated_nav,
        estimated_change_pct=benchmark_return,
        method=f"v_active_bench_{benchmark_key}",
        benchmark=benchmark_key,
    )
