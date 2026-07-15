"""东方财富基金档案 —— 季报完整持仓 + 占净值比例。

与 holding.py 的区别：不限制 topline，尽量抓全所有披露的重仓股，
并计算 covered_weight（已覆盖的净值比例合计）与 uncovered_weight（长尾）。

对齐 ITERATIONS.md：v_top10 只覆盖 53.51%，剩余 ~42% 是误差主要来源。
holdings_full 帮助 v_residual_uncovered / v_index_blend 做「长尾代理」。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from ..cache import CsvCache, http_get
from ...core.models import FundHolding, _guess_market
from .holding import _parse_holdings, ARCHIVE_URL, REFERER


@dataclass
class FullHoldings:
    """完整持仓视图。"""

    fund_code: str
    report_date: str
    holdings: list[FundHolding]

    @property
    def covered_weight_pct(self) -> float:
        """已披露持仓占净值比例合计（百分数）。"""
        return sum(h.weight_pct for h in self.holdings)

    @property
    def uncovered_weight_pct(self) -> float:
        """未覆盖长尾占净值比例（百分数），至少为 0。

        这里以「股票总仓位约 95%」为上界估计（LOF 160223 招募书：股票 ≥85%）。
        """
        stock_position = 95.0
        return max(0.0, stock_position - self.covered_weight_pct)


def fetch_full_holdings(
    fund_code: str,
    *,
    topline: int = 100,
    cache: Optional[CsvCache] = None,
    force: bool = False,
) -> FullHoldings:
    """抓取基金完整持仓（尽可能多，默认上限 100 只）。"""
    cache = cache or CsvCache()

    def _fetch() -> list[dict]:
        url = ARCHIVE_URL.format(code=fund_code, topline=topline)
        text = http_get(url, encoding="utf-8", referer=REFERER.format(code=fund_code))
        return _parse_holdings(text, topline)

    rows = cache.get_or_fetch(
        namespace="holding_full",
        key=f"{fund_code}_{topline}",
        fetch=_fetch,
        fieldnames=["stock_code", "stock_name", "weight_pct", "market", "report_date"],
        force=force,
    )

    holdings = [
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
    report_date = holdings[0].report_date if holdings else ""
    return FullHoldings(fund_code=fund_code, report_date=report_date, holdings=holdings)
