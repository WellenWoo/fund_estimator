"""data_sources/benchmark/get_benchmark.py — 多 benchmark 行情拉取

主动基金需要候选多个 benchmark, 自动选优。
候选: 沪深300 / 中证500 / 中证1000 / 创业板指 / 上证50
"""
from __future__ import annotations
from datetime import date as Date
from typing import Optional

from data_sources.sina.history import fetch_kline, get_close_on, get_return_pct
from core.config import BENCHMARKS


def list_benchmarks() -> list[tuple[str, str]]:
    """返回 [(key, name), ...]"""
    return list(BENCHMARKS.items())


def benchmark_return(benchmark_key: str, start: Date, end: Date) -> Optional[float]:
    """某 benchmark 在 [start, end] 区间的涨跌幅。"""
    if benchmark_key not in BENCHMARKS:
        return None
    code, _ = BENCHMARKS[benchmark_key]
    return get_return_pct(code, start, end)


def benchmark_close(benchmark_key: str, target_date: Date) -> Optional[float]:
    """某 benchmark 在 target_date 的收盘价。"""
    if benchmark_key not in BENCHMARKS:
        return None
    code, _ = BENCHMARKS[benchmark_key]
    return get_close_on(code, target_date)
