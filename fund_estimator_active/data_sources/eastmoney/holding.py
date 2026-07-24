"""data_sources/eastmoney/holding.py — 轻量前 10 大持仓

通过 fund.eastmoney.com/pingzhongdata/{code}.js 拉取
返回: StockPosition 列表, 权重从资产配置数据估算
"""
from __future__ import annotations
import re
import json
import urllib.request
from datetime import date as Date
from typing import Optional

from core.models import StockPosition, FundHolding
from core.config import EAST_PINGZHONG


def fetch_top10(fund_code: str = "160211", timeout: int = 10) -> list[StockPosition]:
    """从 pingzhongdata JS 解析 top10 持仓。
    
    返回: 包含股票代码、名称（暂用代码）和估算权重的 StockPosition 列表
    """
    url = f"{EAST_PINGZHONG}/{fund_code}.js?v={Date.today().isoformat()}"
    req = urllib.request.Request(url, headers={"Referer": "https://fund.eastmoney.com/"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8", errors="ignore")

    m = re.search(r"stockCodes\s*=\s*\[([^\]]+)\]", raw)
    if not m:
        return []
    raw_codes = m.group(1)
    items = re.findall(r'"(\d{6})(\d?)"', raw_codes)

    stock_ratio = 0.95
    m_asset = re.search(r'Data_assetAllocation\s*=\s*([^;]+);', raw)
    if m_asset:
        try:
            asset_data = json.loads(m_asset.group(1))
            for series in asset_data.get("series", []):
                if series.get("name") == "股票占净比":
                    data = series.get("data", [])
                    if data:
                        stock_ratio = data[-1] / 100.0
                        break
        except Exception:
            pass

    positions: list[StockPosition] = []
    for i, (code, marker) in enumerate(items[:10]):
        avg_weight = (stock_ratio * 100.0) / min(len(items), 10) if items else 0.0
        positions.append(StockPosition(code=code, name=code, weight_pct=avg_weight))
    return positions


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
    m = re.search(r"Data_fundSharesPositions\s*=\s*(\[[^\]]+\](?:,\[[^\]]+\])*)", raw)
    if m:
        last = re.findall(r'\],?\[(\d+),([\d\.]+)\]', m.group(1))
        if last:
            meta["stock_position_pct"] = float(last[-1][1])
    return meta
