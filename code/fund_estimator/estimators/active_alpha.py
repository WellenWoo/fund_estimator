"""v_active_alpha：top10 + 长尾×(benchmark + 历史 alpha)。

对长尾建模为：benchmark 涨跌 + 经理历史 alpha。
alpha_drift: 经理历史日均 alpha（decimal, e.g. 0.0005 = 0.05%/天）
"""
from __future__ import annotations

from typing import Optional, Dict

from ..core.models import NAVEstimate


def estimate_v_active_alpha(
    holdings: list,
    t1_nav: float,
    today: str,
    t1_date: str,
    quotes: Dict[str, float],
    benchmark_return: float,
    benchmark_key: str,
    alpha_drift: float = 0.0,
    stock_position: float = 0.95,
    fund_code: str = "160211",
    fund_name: str = "",
) -> Optional[NAVEstimate]:
    """v_active_alpha：top10 真实 + 长尾用 (benchmark + alpha_drift) 代理。"""
    if hasattr(holdings, 'top10'):
        top10_list = holdings.top10()
    elif isinstance(holdings, list):
        top10_list = holdings[:10]
    else:
        return None

    if not top10_list:
        return None

    sp = stock_position

    top10_contrib = 0.0
    total_top10_w = 0.0
    for p in top10_list:
        code = getattr(p, 'code', None) or (p[0] if isinstance(p, (list, tuple)) else None)
        weight_pct = getattr(p, 'weight_pct', None) or (p[2] if isinstance(p, (list, tuple)) else 0.0)
        r = quotes.get(code, 0.0)
        w = weight_pct / 100.0
        top10_contrib += w * r
        total_top10_w += w

    residual_w = max(sp - total_top10_w, 0.0)
    residual_change = benchmark_return + alpha_drift
    est_change = top10_contrib + residual_w * residual_change

    estimated_nav = t1_nav * (1 + est_change)
    return NAVEstimate(
        fund_code=fund_code,
        today=today,
        t1_date=t1_date,
        t1_nav=round(t1_nav, 6),
        estimated_nav=round(estimated_nav, 6),
        estimated_change_pct=round(est_change * 100.0, 4),
        method="v_active_alpha",
        detail={
            "benchmark": benchmark_key,
            "alpha_drift": alpha_drift,
            "covered_weight": round(total_top10_w, 4),
            "residual_weight": round(residual_w, 4),
        },
    )
