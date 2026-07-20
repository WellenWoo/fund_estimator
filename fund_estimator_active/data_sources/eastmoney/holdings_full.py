"""data_sources/eastmoney/holdings_full.py — 完整季报持仓

通过 FundArchivesDatas.aspx?type=quarter 拉取
返回: FundHolding (含名称 + 占比 + 持股数 + 持仓市值)
"""
from __future__ import annotations
import re
import urllib.request
from datetime import date as Date, datetime

from core.models import FundHolding, StockPosition
from core.config import EAST_FUND_BASE


def fetch_full_holdings(fund_code: str = "160211", report_date: Date | None = None,
                        timeout: int = 15) -> FundHolding | None:
    """拉取指定季报的全部持仓。"""
    url = (f"{EAST_FUND_BASE}/FundArchivesDatas.aspx?type=quarter&mode=0&code={fund_code}"
           f"&rt={datetime.now().timestamp()}")
    req = urllib.request.Request(url, headers={"Referer": f"{EAST_FUND_BASE}/{fund_code}.html",
                                                "User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("gbk", errors="ignore")
    except Exception:
        return None

    # 找所有季报日期
    periods = re.findall(r"var apidata\s*=\s*\{[^}]*?\"(20\d{2}-\d{2}-\d{2})\"", raw)
    if not periods:
        # 备选: 某些版本是 [[date, [...rows]], ...] 结构
        m = re.search(r"var apidata\s*=\s*\[(.*?)\];\s*$", raw, re.S)
        if not m:
            return None
        body = m.group(1)
        # 解析 [[date, [[code, name, pct], ...]], ...]
        blocks = re.findall(r'\"(20\d{2}-\d{2}-\d{2})\"\s*,\s*\[\[(.*?)\](?:,\[(.*?)\])*\]', body, re.S)
        if not blocks:
            return None
        latest_date_str = blocks[0][0]
        latest_body = blocks[0][1]
    else:
        latest_date_str = periods[0]
        # 找该日期对应的 holdings 段
        idx = raw.find(latest_date_str)
        body = raw[idx:idx+50000]
        latest_body = body

    latest_date = Date.fromisoformat(latest_date_str)

    # 解析 [code, name, pct, shares, market_value, ...]
    rows = re.findall(
        r'\\"(\d{6})\\"\\s*,\\s*\\"([^\\"]+)\\"\\s*,\\s*\\"([\d\.]+)\\"\\s*'
        r'(?:,\\s*\\"([\d]+)\\"\\s*)?(?:,\\s*\\"([\d\.]+)\\"\\s*)?',
        latest_body
    )
    # 备选: 不带转义符
    if not rows:
        rows = re.findall(
            r'"(\d{6})"\s*,\s*"([^"]+)"\s*,\s*"([\d\.]+)"\s*'
            r'(?:,\s*"(\d+)"\s*)?(?:,\s*"([\d\.]+)"\s*)?',
            latest_body
        )

    if not rows:
        return None

    positions = []
    for r in rows:
        code, name, pct, shares, mv = r[0], r[1], float(r[2]), r[3] if r[3] else "0", r[4] if r[4] else "0"
        positions.append(StockPosition(
            code=code, name=name, weight_pct=pct,
            shares=int(shares), market_value=float(mv)
        ))

    return FundHolding(
        fund_code=fund_code, fund_name="",
        report_date=latest_date,
        positions=positions,
    )
