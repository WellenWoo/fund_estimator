"""estimators/blend.py — v_active_top10_blend + v_active_top10_resid (主推)

核心思路:
  已知 top10 真实涨跌 + 假设长尾 ≈ benchmark 涨跌
  用 alpha 控制长尾用 benchmark 代理的强度
  alpha ∈ [0, 1]
    alpha = 0  →  长尾视为现金/债券 (收益为0)
    alpha = 1  →  长尾完全跟随 benchmark

公式 (v_active_top10_blend):
  top10_contrib = Σᵢ (wᵢ / 100) × rᵢ        (wᵢ = 占净值比例)
  residual_w    = max(stock_pos - top10_cov, 0)
  est_change    = top10_contrib + alpha × residual_w × benchmark_return
  est_nav       = t1_nav × (1 + est_change)

公式 (v_active_top10_resid):
  top10_contrib     = Σᵢ (wᵢ / 100) × rᵢ
  residual_weight   = max(stock_pos - top10_cov, 0)
  est_change        = top10_contrib + residual_weight × bench_return
"""
from __future__ import annotations
from datetime import date as Date
from typing import Optional

from core.models import FundHolding, NAVEstimate


def estimate_v_active_top10_blend(holding: FundHolding, t1_nav: float, today: Date,
                                  t1_date: Date, quotes: dict[str, float],
                                  benchmark_return: float, benchmark_key: str,
                                  alpha: float = 0.5) -> Optional[NAVEstimate]:
    """v_active_top10_blend: top10 真实贡献 + alpha × 长尾 benchmark 代理。

    Args:
        alpha:  长尾代理强度 (推荐 0.4 ~ 0.6, 由 tune_benchmark.py 校准)
                alpha=0: 长尾视为现金/债券(收益0)
                alpha=1: 长尾完全跟随 benchmark
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
    est_change = top10_contrib + alpha * residual_w * benchmark_return

    estimated_nav = t1_nav * (1 + est_change)

    return NAVEstimate(
        fund_code=holding.fund_code, fund_name=holding.fund_name,
        today=today, t1_date=t1_date, t1_nav=t1_nav,
        estimated_nav=estimated_nav,
        estimated_change_pct=est_change,
        method="v_active_top10_blend",
        benchmark=benchmark_key,
        alpha=alpha,
    )


def estimate_v_active_top10_resid(holding: FundHolding, t1_nav: float, today: Date,
                                  t1_date: Date, quotes: dict[str, float],
                                  benchmark_return: float, benchmark_key: str) -> Optional[NAVEstimate]:
    """v_active_top10_resid: top10 真实 + 残差用 benchmark 真实按权重分配。

    与 blend 的区别:
      - blend 用 alpha 控制长尾代理强度
      - resid 长尾完全跟随 benchmark (等价于 blend alpha=1.0)
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
    est_change = top10_contrib + residual_w * benchmark_return

    estimated_nav = t1_nav * (1 + est_change)
    return NAVEstimate(
        fund_code=holding.fund_code, fund_name=holding.fund_name,
        today=today, t1_date=t1_date, t1_nav=t1_nav,
        estimated_nav=estimated_nav,
        estimated_change_pct=est_change,
        method=f"v_active_top10_resid_{benchmark_key}",
        benchmark=benchmark_key,
    )
