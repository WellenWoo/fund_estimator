"""本地 CSV 缓存：把外部接口拉到的历史数据落盘，避免反复被限流。

约定：
- 目录: /workspace/code/fund_estimator/.cache/
- 文件命名:
    kline_{symbol}.csv  — 股票日线（symbol 带 sh/sz 前缀）
    lsjz_{code}.csv     — 基金历史净值
- 格式：csv with header
"""

from __future__ import annotations

import csv
import os
import time
from pathlib import Path

CACHE_DIR = Path(__file__).resolve().parent.parent / ".cache"
CACHE_DIR.mkdir(exist_ok=True)
TTL_SECONDS = 24 * 3600  # 缓存 24 小时


def cache_path(name: str) -> Path:
    return CACHE_DIR / name


def read_csv(name: str) -> list[dict] | None:
    p = cache_path(name)
    if not p.exists():
        return None
    age = time.time() - p.stat().st_mtime
    if age > TTL_SECONDS:
        return None
    with p.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def write_csv(name: str, rows: list[dict]) -> None:
    p = cache_path(name)
    if not rows:
        return
    keys = list(rows[0].keys())
    with p.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=keys)
        writer.writeheader()
        for r in rows:
            writer.writerow({k: r.get(k, "") for k in keys})


def clear_cache() -> int:
    n = 0
    for f in CACHE_DIR.glob("*.csv"):
        f.unlink()
        n += 1
    return n
