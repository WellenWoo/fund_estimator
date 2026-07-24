"""v_active_top10：纯持仓还原，忽略长尾。

公式：
  est_change = Σᵢ (wᵢ / 100) × rᵢ        (wᵢ = 占净值比例, 仅 top10)
  est_nav    = t1_nav × (1 + est_change)
"""
from __future__ import annotations

from typing import Optional, Dict

from ..core.models import NAVEstimate


def estimate_v_active_top10(
    holdings: list,
    t1_nav: float,
    today: str,
    t1_date: str,
    quotes: Dict[str, float],
    fund_code: str = "160211",
    fund_name: str = "",
) -> Optional[NAVEstimate]:
    """v_active_top10: 用前 10 大持仓真实涨跌加权。

    Args:
        holdings: 兼容两种持仓结构：
            - FundHolding 对象（主项目）
            - list[FundHolding] 或 [holding_obj]（active module）
        t1_nav: T-1 NAV
        today: 估值日字符串
        t1_date: T-1 日期字符串
        quotes: {stock_code: 今日涨跌幅(decimal)}
    """
    # 兼容主项目的 FundHolding 和 active module 的 holding.top10()
    if hasattr(holdings, 'top10'):
        top10_list = holdings.top10()
    elif isinstance(holdings, list):
        top10_list = holdings[:10]
    else:
        return None

    if not top10_list:
        return None

    est_change = 0.0
    total_w = 0.0
    for p in top10_list:
        code = getattr(p, 'code', None) or (p[0] if isinstance(p, (list, tuple)) else None)
        weight_pct = getattr(p, 'weight_pct', None) or (p[2] if isinstance(p, (list, tuple)) else 0.0)
        r = quotes.get(code, 0.0)
        w = weight_pct / 100.0
        est_change += w * r
        total_w += w

    if total_w <= 0:
        return None

    estimated_nav = t1_nav * (1 + est_change)
    return NAVEstimate(
        fund_code=fund_code,
        today=today,
        t1_date=t1_date,
        t1_nav=round(t1_nav, 6),
        estimated_nav=round(estimated_nav, 6),
        estimated_change_pct=round(est_change * 100.0, 4),
        method="v_active_top10",
        detail={"covered_weight": round(total_w, 4)},
    )
