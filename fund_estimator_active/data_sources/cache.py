"""data_sources/cache.py — 本地 CSV 缓存层

约定:  所有外部 API 调用 → 先查 .cache/{name}.csv, 命中且未过期 → 直接返回; 否则拉取。
TTL 按数据类型区分:
  - lsjz (NAV 历史): 7 天 (数据变化慢)
  - kline (K 线): 24 小时 (每日更新)
  - holding (持仓): 30 天 (季度数据)
  - daily_log: 不缓存 (追加写入)
force=True 强制刷新, 仅用于首次大样本回填, 日常脚本请勿开启。
"""
from __future__ import annotations
import csv
import json
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Iterable, Optional

from core.config import CACHE_DIR, CACHE_TTL_HOURS

_CACHE_TTL_MAP = {
    "lsjz": 168,
    "kline": 24,
    "holding": 30 * 24,
    "daily_log": 0,
}


def _cache_path(name: str) -> Path:
    return CACHE_DIR / f"{name}.csv"


def _get_ttl(name: str, default_ttl: int) -> int:
    for key, ttl in _CACHE_TTL_MAP.items():
        if key in name:
            return ttl
    return default_ttl


def is_fresh(name: str, ttl_hours: int = None) -> bool:
    """缓存是否存在且未过期。
    
    Args:
        name: 缓存名称
        ttl_hours: 自定义 TTL（小时），不指定则按类型推断
    """
    p = _cache_path(name)
    if not p.exists():
        return False
    if ttl_hours is None:
        ttl_hours = _get_ttl(name, CACHE_TTL_HOURS)
    if ttl_hours == 0:
        return False
    age = time.time() - p.stat().st_mtime
    return age < ttl_hours * 3600


def save_rows(name: str, rows: list[dict], fieldnames: Optional[list[str]] = None) -> None:
    """保存 dict 列表到 CSV, 自动推断列名 (取首行的 keys)。"""
    if not rows:
        return
    if fieldnames is None:
        fieldnames = list(rows[0].keys())
    p = _cache_path(name)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for row in rows:
            w.writerow(row)


def load_rows(name: str) -> list[dict]:
    """读取缓存为 dict 列表。"""
    p = _cache_path(name)
    if not p.exists():
        return []
    with p.open("r", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def append_row(name: str, row: dict) -> None:
    """追加一行 (不覆盖, 用于 daily_log)。"""
    p = _cache_path(name)
    p.parent.mkdir(parents=True, exist_ok=True)
    is_new = not p.exists()
    with p.open("a", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(row.keys()))
        if is_new:
            w.writeheader()
        w.writerow(row)


def cache_age_hours(name: str) -> float:
    p = _cache_path(name)
    if not p.exists():
        return float("inf")
    return (time.time() - p.stat().st_mtime) / 3600
