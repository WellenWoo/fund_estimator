"""estimators/alpha_residual.py — v_active_alpha

v_active_alpha:  top10 真实涨跌 + (1 - top10_cov) × (benchmark + 历史 alpha)
对长尾建模为:  benchmark 涨跌 + 经理历史 alpha。
需要先在训练期估计 alpha_drift, 然后应用到估值。
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
    top10_cov = min(sum(p.weight_pct for p in top10) / 100.0, 1.0)  # 转 decimal
    # 季报股票总仓位 (扣现金)
    stock_pos = holding.stock_position_pct / 100.0 if holding.stock_position_pct else top10_cov + 0.1

    # 已知部分: top10 加权真实涨跌
    top10_total_w = sum(p.weight_pct for p in top10)
    known_change = 0.0
    for p in top10:
        r = quotes.get(p.code, 0.0)
        known_change += (p.weight_pct / top10_total_w) * r if top10_total_w > 0 else 0.0

    # 长尾 = stock_pos - top10_cov, 用 (benchmark + alpha) 代理
    residual_weight = max(stock_pos - top10_cov, 0.0)
    residual_change = benchmark_return + alpha_drift

    # 综合
    #   total = top10_cov × known_change + residual_weight × residual_change + (1 - stock_pos) × 0
    est_change = top10_cov * known_change + residual_weight * residual_change

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
