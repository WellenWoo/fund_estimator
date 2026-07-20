"""data_sources/eastmoney/holding.py — 轻量前 10 大持仓

通过 fund.eastmoney.com/pingzhongdata/{code}.js 拉取
返回: StockPosition 列表, 无 shares / market_value
"""
from __future__ import annotations
import re
import urllib.request
from datetime import date as Date
from typing import Optional

from core.models import StockPosition, FundHolding
from core.config import EAST_PINGZHONG


def fetch_top10(fund_code: str = "160211", timeout: int = 10) -> list[StockPosition]:
    """从 pingzhongdata JS 解析 top10 持仓 (只有代码, 没有名称/占比)。"""
    url = f"{EAST_PINGZHONG}/{fund_code}.js?v={Date.today().isoformat()}"
    req = urllib.request.Request(url, headers={"Referer": "https://fund.eastmoney.com/"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8", errors="ignore")

    m = re.search(r"stockCodes\s*=\s*\[([^\]]+)\]", raw)
    if not m:
        return []
    raw_codes = m.group(1)
    items = re.findall(r'"(\d{6})(\d?)"', raw_codes)

    positions: list[StockPosition] = []
    for code, marker in items:
        # marker: 0=SZ, 1=SH, 0 with sz prefix inferred
        positions.append(StockPosition(code=code, name=code, weight_pct=0.0))
    return positions[:10]


def fetch_fund_meta(fund_code: str = "160211", timeout: int = 10) -> dict:
    """提取基金名称, 费率, 股票仓位图等。"""
    url = f"{EAST_PINGZHONG}/{fund_code}.js?v={Date.today().isoformat()}"
    req = urllib.request.Request(url, headers={"Referer": "https://fund.eastmoney.com/"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8", errors="ignore")

    meta: dict = {}
    m = re.search(r'fS_name\s*=\s*"([^"]+)"', raw)
    if m:
        meta["name"] = m.group(1)
    m = re.search(r'syl_1n\s*=\s*"([\d\.\-]+)"', raw)
    if m:
        meta["return_1y"] = float(m.group(1))
    # 股票仓位图: [[ts, pct], ...] → 最新 pct
    m = re.search(r"Data_fundSharesPositions\s*=\s*(\[[^\]]+\](?:,\[[^\]]+\])*)", raw)
    if m:
        last = re.findall(r'\],?\[(\d+),([\d\.]+)\]', m.group(1))
        if last:
            meta["stock_position_pct"] = float(last[-1][1])
    return meta
