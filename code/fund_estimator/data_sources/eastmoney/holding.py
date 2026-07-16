"""东方财富数据源：基金持仓、净值历史、股票仓位测算。

主要接口（实测可用 2026-07-06）：
- https://fund.eastmoney.com/pingzhongdata/{code}.js       JS 伪 JS 变量
- https://fundf10.eastmoney.com/FundArchivesDatas.aspx?...  HTML 表格
"""

from __future__ import annotations

import json
import re
from datetime import date, datetime
from typing import Optional
from urllib.request import Request, urlopen

from ...core.models import FundHolding, StockPosition

PINGZHONG_URL = "https://fund.eastmoney.com/pingzhongdata/{code}.js"
DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Referer": "https://fund.eastmoney.com/",
}


def fetch_pingzhong_js(fund_code: str, timeout: float = 15.0) -> str:
    """拉取并解析东方财富的 pingzhongdata JS（包含持仓、净值历史）。"""
    url = PINGZHONG_URL.format(code=fund_code)
    req = Request(url, headers=DEFAULT_HEADERS)
    with urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("utf-8", errors="ignore")
    return raw


def parse_stock_codes(js_text: str) -> list[StockPosition]:
    """从 pingzhongdata JS 中抽取前 10 大持仓股票代码。

    返回的代码格式:
        - 原始 stockCodes 字段末尾带一个尾随的 '0'（例如 "3007500"），
          这是因为东方财富旧版是 7 位代码，新版是 6 位；新版字段 stockCodesNew 是 "0.300750"。
        - 我们以新版为准。
    """
    m = re.search(r"stockCodesNew\s*=\s*\[(.*?)\]", js_text, re.S)
    positions = []
    if m:
        raw = m.group(1)
        for token in re.findall(r'"([^"]+)"', raw):
            # 格式 0.300750 或 1.600519
            if "." in token:
                market_bit, code = token.split(".", 1)
                market = "SZ" if market_bit == "0" else "SH"
                positions.append(
                    StockPosition(code=code, name="", market=market)
                )
    return positions


def parse_stock_position_pct(js_text: str) -> float:
    """从 Data_fundSharesPositions 抽取最新的股票仓位测算（%）。

    Data_fundSharesPositions = [[timestamp_ms, pct], ...]
    """
    m = re.search(r"Data_fundSharesPositions\s*=\s*\[(.*?)\];", js_text, re.S)
    if not m:
        return 0.0
    body = m.group(1)
    # 找最后一个二维数组
    tuples = re.findall(r"\[\s*(\d+)\s*,\s*([\d.]+)\s*\]", body)
    if not tuples:
        return 0.0
    return float(tuples[-1][1])


def parse_fund_basic(js_text: str, fund_code: str) -> FundHolding:
    """提取基金名称 + 股票仓位 + 持仓股票列表。"""
    name_match = re.search(r'fS_name\s*=\s*"([^"]+)"', js_text)
    fund_name = name_match.group(1) if name_match else ""

    positions = parse_stock_codes(js_text)
    pct = parse_stock_position_pct(js_text)

    return FundHolding(
        fund_code=fund_code,
        fund_name=fund_name,
        report_date=date.today(),  # 占位
        disclose_date=date.today(),
        stock_positions=positions,
        stock_position_pct=pct,
        source="eastmoney/pingzhongdata",
    )


def fetch_top_holdings(fund_code: str, top_n: int = 10, timeout: float = 15.0) -> FundHolding:
    """只取前 top_n 大持仓。东方财富接口本身只返回前 10，但保留接口一致性。"""
    js_text = fetch_pingzhong_js(fund_code, timeout=timeout)
    holding = parse_fund_basic(js_text, fund_code)
    holding.stock_positions = holding.stock_positions[:top_n]
    return holding


if __name__ == "__main__":
    import sys
    code = sys.argv[1] if len(sys.argv) > 1 else "160223"
    h = fetch_top_holdings(code)
    print(f"基金: {h.fund_name} ({h.fund_code})")
    print(f"股票仓位: {h.stock_position_pct}%")
    print(f"持仓股票: {[p.code for p in h.stock_positions]}")
