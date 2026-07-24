"""v_active_top10_blend + v_active_top10_resid：主推 + 残差。

核心思路：
  已知 top10 真实涨跌 + 假设长尾 ≈ benchmark 涨跌
  用 alpha 控制长尾用 benchmark 代理的强度
  alpha ∈ [0, 1]
    alpha = 0  →  长尾视为现金/债券 (收益为0)
    alpha = 1  →  长尾完全跟随 benchmark

公式 (v_active_top10_blend):
  top10_contrib = Σᵢ (wᵢ / 100) × rᵢ
  residual_w    = max(stock_pos - top10_cov, 0)
  est_change    = top10_contrib + alpha × residual_w × benchmark_return

公式 (v_active_top10_resid):
  est_change = top10_contrib + residual_weight × bench_return
  （等价于 blend alpha=1.0）
"""
from __future__ import annotations

from typing import Optional, Dict

from ..core.models import NAVEstimate


def estimate_v_active_top10_blend(
    holdings: list,
    t1_nav: float,
    today: str,
    t1_date: str,
    quotes: Dict[str, float],
    benchmark_return: float,
    benchmark_key: str,
    stock_position: float = 0.95,
    alpha: float = 0.5,
    fund_code: str = "160211",
    fund_name: str = "",
) -> Optional[NAVEstimate]:
    """v_active_top10_blend：top10 真实贡献 + α × 长尾 benchmark 代理。"""
    if hasattr(holdings, 'top10'):
        top10_list = holdings.top10()
    elif isinstance(holdings, list):
        top10_list = holdings[:10]
    else:
        return None

    if not top10_list:
        return None

    # 股票总仓位（默认 0.95，主动基金一般 80-95%）
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
    est_change = top10_contrib + alpha * residual_w * benchmark_return

    estimated_nav = t1_nav * (1 + est_change)
    return NAVEstimate(
        fund_code=fund_code,
        today=today,
        t1_date=t1_date,
        t1_nav=round(t1_nav, 6),
        estimated_nav=round(estimated_nav, 6),
        estimated_change_pct=round(est_change * 100.0, 4),
        method="v_active_top10_blend",
        detail={
            "benchmark": benchmark_key,
            "alpha": alpha,
            "covered_weight": round(total_top10_w, 4),
            "residual_weight": round(residual_w, 4),
            "top10_contrib_pct": round(top10_contrib * 100.0, 4),
        },
    )


def estimate_v_active_top10_resid(
    holdings: list,
    t1_nav: float,
    today: str,
    t1_date: str,
    quotes: Dict[str, float],
    benchmark_return: float,
    benchmark_key: str,
    stock_position: float = 0.95,
    fund_code: str = "160211",
    fund_name: str = "",
) -> Optional[NAVEstimate]:
    """v_active_top10_resid：top10 真实 + 残差完全跟随 benchmark (alpha=1)。"""
    return estimate_v_active_top10_blend(
        holdings=holdings,
        t1_nav=t1_nav,
        today=today,
        t1_date=t1_date,
        quotes=quotes,
        benchmark_return=benchmark_return,
        benchmark_key=benchmark_key,
        stock_position=stock_position,
        alpha=1.0,
        fund_code=fund_code,
        fund_name=fund_name,
    )
