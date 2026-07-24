"""estimators/alpha_residual.py — v_active_alpha

v_active_alpha:  top10 真实涨跌 + 长尾 × (benchmark + 历史 alpha)
对长尾建模为:  benchmark 涨跌 + 经理历史 alpha。
需要先在训练期估计 alpha_drift, 然后应用到估值。

公式:
  top10_contrib = Σᵢ (wᵢ / 100) × rᵢ
  residual_w    = max(stock_pos - top10_cov, 0)
  est_change    = top10_contrib + residual_w × (benchmark_return + alpha_drift)
"""
from __future__ import annotations
from datetime import date as Date
from typing import Optional

from core.models import FundHolding, NAVEstimate


def estimate_v_active_alpha(holding: FundHolding, t1_nav: float, today: Date,
                            t1_date: Date, quotes: dict[str, float],
                            benchmark_return: float, benchmark_key: str,
                            alpha_drift: float = 0.0) -> Optional[NAVEstimate]:
    """v_active_alpha: top10 真实 + 长尾用 (benchmark + alpha_drift) 代理。

    Args:
        holding:           季报持仓
        t1_nav:            T-1 NAV
        today:             估值日
        t1_date:           T-1 日期
        quotes:            {stock_code: 今日涨跌幅}
        benchmark_return:  benchmark 涨跌幅
        alpha_drift:       经理历史日均 alpha (decimal, e.g. 0.0005 = 0.05%/天)
    """
    top10 = holding.top10()
    if not top10:
        return None

    stock_pos = holding.stock_position_pct / 100.0 if holding.stock_position_pct else 0.95

    top10_contrib = 0.0
    total_top10_w = 0.0
    for p in top10:
        r = quotes.get(p.code, 0.0)
        w = p.weight_pct / 100.0
        top10_contrib += w * r
        total_top10_w += w

    residual_w = max(stock_pos - total_top10_w, 0.0)
    residual_change = benchmark_return + alpha_drift

    est_change = top10_contrib + residual_w * residual_change

    estimated_nav = t1_nav * (1 + est_change)
    return NAVEstimate(
        fund_code=holding.fund_code, fund_name=holding.fund_name,
        today=today, t1_date=t1_date, t1_nav=t1_nav,
        estimated_nav=estimated_nav,
        estimated_change_pct=est_change,
        method="v_active_alpha",
        benchmark=benchmark_key,
        alpha=alpha_drift,
    )
