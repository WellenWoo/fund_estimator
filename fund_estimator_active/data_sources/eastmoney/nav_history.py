"""data_sources/eastmoney/nav_history.py — 历史净值 (分页全量)

API: api.fund.eastmoney.com/f10/lsjz
返回: list[{date, nav, change_pct, ...}]
"""
from __future__ import annotations
import json
import urllib.request
import urllib.parse
from datetime import date as Date, datetime
from typing import Optional

from data_sources import cache
from core.config import EAST_LSJZ_API, CACHE_TTL_HOURS


def fetch_history(fund_code: str = "160211",
                  start: Date = Date(2026, 4, 1),
                  end: Date = Date(2026, 7, 31),
                  page_size: int = 20,
                  force: bool = False,
                  timeout: int = 15) -> list[dict]:
    """拉取全量历史净值, 走分页。

    Args:
        force: True 强制刷新缓存,  False 走 24h 缓存。
    """
    cache_name = f"lsjz_{fund_code}"

    if not force and cache.is_fresh(cache_name):
        rows = cache.load_rows(cache_name)
        # 转 date
        out = []
        for r in rows:
            r2 = dict(r)
            for k in ("date",):
                if k in r2 and r2[k]:
                    try:
                        r2[k] = Date.fromisoformat(r2[k])
                    except Exception:
                        pass
            for k in ("nav", "change_pct"):
                if k in r2 and r2[k]:
                    try:
                        r2[k] = float(r2[k])
                    except Exception:
                        r2[k] = 0.0
            out.append(r2)
        if out:
            return out

    all_rows: list[dict] = []
    page = 1
    while True:
        params = {
            "fundCode": fund_code,
            "pageIndex": str(page),
            "pageSize": str(page_size),
            "mode": "0",
            "sdate": start.isoformat(),
            "edate": end.isoformat(),
        }
        url = EAST_LSJZ_API + "?" + urllib.parse.urlencode(params)
        req = urllib.request.Request(url, headers={
            "Referer": f"https://fundf10.eastmoney.com/{fund_code}.html",
            "User-Agent": "Mozilla/5.0",
        })
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read())
        except Exception as e:
            print(f"[nav_history] page {page} failed: {e}")
            break

        lst = data.get("Data", {}).get("LSJZList", [])
        if not lst:
            break
        early_stop = False
        for row in lst:
            rdate_str = row.get("FSRQ")
            # 早停: 日期已早于 start
            if rdate_str and Date.fromisoformat(rdate_str) < start:
                early_stop = True
                break
            all_rows.append({
                "date": rdate_str,
                "nav": float(row.get("DWJZ", 0) or 0),
                "change_pct": float(row.get("JZZZL", 0) or 0),
                "ljjz": float(row.get("LJJZ", 0) or 0),
            })
        if early_stop:
            break

        if len(lst) < 20:  # API 固定最多 20 行/页
            break
        page += 1
        if page > 100:
            break

    # 落盘
    if all_rows:
        cache.save_rows(cache_name, all_rows, fieldnames=["date", "nav", "change_pct", "ljjz"])

    # 转 date
    out = []
    for r in all_rows:
        r2 = dict(r)
        if r2.get("date"):
            try:
                r2["date"] = Date.fromisoformat(r2["date"])
            except Exception:
                pass
        out.append(r2)
    return out
