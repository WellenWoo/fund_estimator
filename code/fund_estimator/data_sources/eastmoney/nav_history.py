"""天天基金 / 东方财富 —— 历史净值 API（含分页）。

接口（github_code.md §9）::

    http://api.fund.eastmoney.com/f10/lsjz?fundCode={code}&pageIndex={i}&pageSize=20

返回 JSON：``{ Data: { LSJZList: [ {FSRQ, DWJZ, LJJZ, JZZZL}, ... ], TotalCount } }``。
- FSRQ  净值日期
- DWJZ  单位净值
- LJJZ  累计净值
- JZZZL 日增长率(%)

ITERATIONS.md 强调「强制单页 20 + 完整分页」，本模块循环抓取所有页。
"""

from __future__ import annotations

import json
import re
from typing import Optional

from ..cache import CsvCache, http_get


LSJZ_URL = (
    "http://api.fund.eastmoney.com/f10/lsjz"
    "?fundCode={code}&pageIndex={page}&pageSize={size}"
    "&startDate={start}&endDate={end}&_=0"
)
REFERER = "http://fundf10.eastmoney.com/jjjz_{code}.html"

_JSONP_STRIP = re.compile(r"^[^{]*|[^}]*$")


def _parse_lsjz(text: str) -> tuple[list[dict], int]:
    """解析 lsjz 返回，返回 (rows, total_count)。"""
    # 接口有时返回 jsonp/裸 JSON，容错剥离
    cleaned = text.strip()
    if not cleaned.startswith("{"):
        cleaned = _JSONP_STRIP.sub("", cleaned)
    data = json.loads(cleaned)
    payload = data.get("Data") or {}
    lst = payload.get("LSJZList") or []
    total = int(data.get("TotalCount") or payload.get("TotalCount") or len(lst))
    rows = []
    for item in lst:
        rows.append(
            {
                "date": item.get("FSRQ", ""),
                "nav": item.get("DWJZ", ""),
                "acc_nav": item.get("LJJZ", ""),
                "change_pct": item.get("JZZZL", ""),
            }
        )
    return rows, total


def _fetch_all_pages(
    fund_code: str,
    start: str,
    end: str,
    size: int = 20,
) -> list[dict]:
    """按 ITERATIONS 要求：单页 size=20，循环翻页抓全区间。"""
    all_rows: list[dict] = []
    page = 1
    while True:
        url = LSJZ_URL.format(code=fund_code, page=page, size=size, start=start, end=end)
        text = http_get(url, encoding="utf-8", referer=REFERER.format(code=fund_code))
        rows, total = _parse_lsjz(text)
        if not rows:
            break
        all_rows.extend(rows)
        if len(all_rows) >= total or len(rows) < size:
            break
        page += 1
        if page > 200:  # 安全上限
            break
    # 去重 + 按日期升序
    seen = {}
    for r in all_rows:
        if r["date"]:
            seen[r["date"]] = r
    return sorted(seen.values(), key=lambda r: r["date"])


def fetch_nav_history(
    fund_code: str,
    start: str = "",
    end: str = "",
    *,
    cache: Optional[CsvCache] = None,
    force: bool = False,
) -> list[dict]:
    """抓取基金历史净值。

    Returns
    -------
    list[dict]
        每项含 ``date`` / ``nav`` / ``acc_nav`` / ``change_pct``，按日期升序。
    """
    cache = cache or CsvCache()
    key = f"{fund_code}_{start or 'all'}_{end or 'all'}"

    def _fetch() -> list[dict]:
        return _fetch_all_pages(fund_code, start, end)

    rows = cache.get_or_fetch(
        namespace="nav_history",
        key=key,
        fetch=_fetch,
        fieldnames=["date", "nav", "acc_nav", "change_pct"],
        force=force,
    )
    # 数值化 & 过滤空 NAV
    out = []
    for r in rows:
        try:
            nav = float(r["nav"])
        except (TypeError, ValueError):
            continue
        out.append(
            {
                "date": r["date"],
                "nav": nav,
                "acc_nav": float(r["acc_nav"]) if r.get("acc_nav") not in ("", None) else nav,
                "change_pct": float(r["change_pct"]) if r.get("change_pct") not in ("", None) else 0.0,
            }
        )
    return out


def build_nav_map(rows: list[dict]) -> dict[str, float]:
    """把 nav_history 行转成 {date: nav} 字典。"""
    return {r["date"]: r["nav"] for r in rows}


def prev_trading_nav(rows: list[dict], target_date: str) -> Optional[tuple[str, float]]:
    """返回 target_date 之前最近一个有净值的交易日 (date, nav)。"""
    prev = None
    for r in rows:
        if r["date"] < target_date:
            prev = (r["date"], r["nav"])
        else:
            break
    return prev
