"""东方财富基金档案 —— 季报前 10 大持仓（轻量抓取）。

接口（github_code.md §9 数据源清单）::

    http://fundf10.eastmoney.com/FundArchivesDatas.aspx?type=jjcc&code={code}&topline=10

返回是一段 JS：``var apidata={ content:"<table>...</table>", ... }``。
用正则从 HTML 表格里解析出 [股票代码, 股票简称, 占净值比例]。

只取前 10 大（README 数据流图：FundHolding 前 10 + 股票仓位 ≈95%）。
"""

from __future__ import annotations

import re
from typing import Optional

from ..cache import CsvCache, http_get
from ...core.models import FundHolding, _guess_market


ARCHIVE_URL = (
    "http://fundf10.eastmoney.com/FundArchivesDatas.aspx"
    "?type=jjcc&code={code}&topline={topline}&year=&month="
)
REFERER = "http://fundf10.eastmoney.com/ccmx_{code}.html"

# 表格行：<td>序号</td><td><a>代码</a></td><td><a>名称</a></td>...<td>占净值比例%</td>
_ROW_RE = re.compile(
    r"<td>\s*\d+\s*</td>\s*"
    r"<td[^>]*>\s*<a[^>]*>(?P<code>\d{6})</a>\s*</td>\s*"
    r"<td[^>]*>\s*<a[^>]*>(?P<name>[^<]+)</a>\s*</td>"
    r".*?(?P<weight>\d+\.\d+)\s*%",
    re.S,
)
_REPORT_RE = re.compile(r"(\d{4}-\d{2}-\d{2})")


def _parse_holdings(js_text: str, topline: int) -> list[dict]:
    """从东方财富返回的 JS 文本解析持仓行。"""
    # 只取第一张表（最新报告期）
    report_date = ""
    m = _REPORT_RE.search(js_text)
    if m:
        report_date = m.group(1)

    rows: list[dict] = []
    for match in _ROW_RE.finditer(js_text):
        code = match.group("code")
        name = match.group("name").strip()
        weight = float(match.group("weight"))
        rows.append(
            {
                "stock_code": code,
                "stock_name": name,
                "weight_pct": weight,
                "market": _guess_market(code),
                "report_date": report_date,
            }
        )
        if len(rows) >= topline:
            break
    return rows


def fetch_top10_holdings(
    fund_code: str,
    *,
    topline: int = 10,
    cache: Optional[CsvCache] = None,
    force: bool = False,
) -> list[FundHolding]:
    """抓取基金前 N（默认 10）大持仓。

    Returns
    -------
    list[FundHolding]
    """
    cache = cache or CsvCache()

    def _fetch() -> list[dict]:
        url = ARCHIVE_URL.format(code=fund_code, topline=topline)
        text = http_get(url, encoding="utf-8", referer=REFERER.format(code=fund_code))
        return _parse_holdings(text, topline)

    rows = cache.get_or_fetch(
        namespace="holding_top10",
        key=f"{fund_code}_{topline}",
        fetch=_fetch,
        fieldnames=["stock_code", "stock_name", "weight_pct", "market", "report_date"],
        force=force,
    )
    return [
        FundHolding(
            stock_code=r["stock_code"],
            stock_name=r["stock_name"],
            weight_pct=float(r["weight_pct"]),
            market=r.get("market", "") or _guess_market(r["stock_code"]),
            report_date=r.get("report_date", ""),
        )
        for r in rows
        if r.get("stock_code")
    ]
