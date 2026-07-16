"""东方财富基金历史净值 API。

URL: http://api.fund.eastmoney.com/f10/lsjz?fundCode=160223&pageIndex=1&pageSize=20

返回 JSON:
    {"Data": {"LSJZList": [{"FSRQ":"2026-07-06", "DWJZ":"2.1875", "JZZZL":"-1.67", ...}, ...],
     "TotalCount": 2343}

本地缓存：.cache/lsjz_{code}.csv
"""

from __future__ import annotations

import json
import sys
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path
from typing import Iterator

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from fund_estimator.data_sources.cache import read_csv, write_csv  # noqa: E402

URL = "http://api.fund.eastmoney.com/f10/lsjz"
HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Referer": "https://fund.eastmoney.com/",
}


def fetch_history(
    fund_code: str,
    start: date | None = None,
    end: date | None = None,
    page_size: int = 20,  # API 强制单页 20
    force: bool = False,
) -> list[dict]:
    """分页拉取历史净值，按日期升序。

    返回每条: {"date": date, "nav": float, "change_pct": float, "bonus": float, "split": float}

    带本地缓存。
    """
    cache_name = f"lsjz_{fund_code}.csv"
    if not force:
        cached = read_csv(cache_name)
        if cached:
            out2 = []
            for r in cached:
                try:
                    out2.append(
                        {
                            "date": date.fromisoformat(r["date"]),
                            "nav": float(r["nav"]) if r["nav"] else None,
                            "change_pct": float(r["change_pct"]) if r["change_pct"] else None,
                            "bonus": float(r.get("bonus") or 0),
                            "split": float(r.get("split") or 1),
                        }
                    )
                except (KeyError, ValueError):
                    continue
            out2.sort(key=lambda r: r["date"])
            # 区间裁剪
            if start or end:
                out2 = [
                    r
                    for r in out2
                    if (start is None or r["date"] >= start)
                    and (end is None or r["date"] <= end)
                ]
            if out2:
                return out2

    out: list[dict] = []
    page = 1
    while True:
        params = {
            "fundCode": fund_code,
            "pageIndex": str(page),
            "pageSize": str(page_size),
            "_": str(int(date.today().strftime("%Y%m%d")) + page),
        }
        if start:
            params["startDate"] = start.isoformat()
        if end:
            params["endDate"] = end.isoformat()
        url = URL + "?" + urllib.parse.urlencode(params)
        req = urllib.request.Request(url, headers=HEADERS)
        with urllib.request.urlopen(req, timeout=15) as resp:
            raw = resp.read().decode("utf-8", errors="ignore")
        try:
            j = json.loads(raw)
        except json.JSONDecodeError:
            break
        rows = j.get("Data", {}).get("LSJZList", [])
        if not rows:
            break
        for r in rows:
            try:
                d = date.fromisoformat(r["FSRQ"])
            except (KeyError, ValueError):
                continue
            out.append(
                {
                    "date": d,
                    "nav": float(r["DWJZ"]) if r.get("DWJZ") else None,
                    "change_pct": float(r["JZZZL"]) if r.get("JZZZL") else None,
                    "bonus": float(r.get("FHFCZ") or 0),
                    "split": float(r.get("FHFCBZ") or 1),
                }
            )
        total = j.get("TotalCount", 0) or 0
        # 防止死循环：超过 total + 5 行就跳
        if len(out) >= total or page > 200:
            break
        page += 1
    out.sort(key=lambda r: r["date"])

    # 写缓存
    if out:
        try:
            write_csv(
                cache_name,
                [
                    {
                        "date": r["date"].isoformat(),
                        "nav": r["nav"] or "",
                        "change_pct": r["change_pct"] if r["change_pct"] is not None else "",
                        "bonus": r["bonus"],
                        "split": r["split"],
                    }
                    for r in out
                ],
            )
        except Exception:
            pass

    # 区间裁剪
    if start or end:
        out = [
            r
            for r in out
            if (start is None or r["date"] >= start) and (end is None or r["date"] <= end)
        ]
    return out


if __name__ == "__main__":
    import sys
    code = sys.argv[1] if len(sys.argv) > 1 else "160223"
    rows = fetch_history(code)
    print(f"=== {code} 共 {len(rows)} 条历史净值 ===")
    for r in rows[-10:]:
        change = f"{r['change_pct']:+.2f}%" if r["change_pct"] is not None else "  -  "
        print(f"  {r['date']}  NAV={r['nav']}  涨跌={change}")
