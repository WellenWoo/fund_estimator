"""estimators/holdings_based.py — v_active_top10

纯持仓还原: 把 top10 持仓按真实涨跌加权, 忽略未披露的仓位(视为现金)。
预期: 误差较大, 适用于"持仓完全披露"且"经理不调仓"的理论场景。

公式:
  est_change = Σᵢ (wᵢ / 100) × rᵢ        (wᵢ = 占净值比例, 仅 top10)
  est_nav    = t1_nav × (1 + est_change)
"""
from __future__ import annotations
from datetime import date as Date
from typing import Optional

from core.models import FundHolding, NAVEstimate


def estimate_v_active_top10(holding: FundHolding, t1_nav: float, today: Date,
                            t1_date: Date, quotes: dict[str, float]) -> Optional[NAVEstimate]:
    """v_active_top10: 用前 10 大持仓真实涨跌加权。

    Args:
        holding: 季报持仓 (含 weight_pct)
        t1_nav: T-1 日单位净值
        today:  估值日
        t1_date: T-1 日期
        quotes: {stock_code: 今日涨跌幅 (decimal, 0.0123 = 1.23%)}

    Returns:
        NAVEstimate (estimated_change_pct 为今日估算的涨跌幅 decimal)
    """
    top10 = holding.top10()
    if not top10:
        return None

    est_change = 0.0
    total_w = 0.0
    for p in top10:
        r = quotes.get(p.code, 0.0)
        w = p.weight_pct / 100.0
        est_change += w * r
        total_w += w

    if total_w <= 0:
        return None

    estimated_nav = t1_nav * (1 + est_change)
    return NAVEstimate(
        fund_code=holding.fund_code,
        fund_name=holding.fund_name,
        today=today,
        t1_date=t1_date,
        t1_nav=t1_nav,
        estimated_nav=estimated_nav,
        estimated_change_pct=est_change,
        method="v_active_top10",
    )
