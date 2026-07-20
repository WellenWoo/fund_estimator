"""estimators/blend.py — v_active_top10_blend + v_active_top10_resid (主推)

核心思路:
  已知 top10 真实涨跌 + 假设长尾 ≈ benchmark 涨跌
  用 alpha 控制长尾用 benchmark 代理的强度
  alpha ∈ [0, 1]
    alpha = 0  →  纯 top10 还原
    alpha = 1  →  100% 用 benchmark 代理 (忽略 top10)
    推荐 alpha ≈ 0.5  (经验值, 由训练期校准)

公式 (v_active_top10_blend):
  est_change = (1-alpha) × top10_avg_change + alpha × benchmark_change
  est_nav    = t1_nav × (1 + est_change)

公式 (v_active_top10_resid):
  top10_contrib     = Σᵢ wᵢ × rᵢ        (wᵢ = 占净值比例 / 100)
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
    """v_active_top10_blend: top10 与 benchmark 的加权混合。

    Args:
        alpha:  长尾代理强度 (推荐 0.4 ~ 0.6, 由 tune_benchmark.py 校准)
    """
    top10 = holding.top10()
    if not top10:
        return None

    # top10 内部归一化加权
    top10_total_w = sum(p.weight_pct for p in top10)
    top10_avg = 0.0
    if top10_total_w > 0:
        for p in top10:
            r = quotes.get(p.code, 0.0)
            top10_avg += (p.weight_pct / top10_total_w) * r

    est_change = (1 - alpha) * top10_avg + alpha * benchmark_return
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
      - blend 把 top10 内部归一化后, 再加 alpha × bench
      - resid 用 top10 在组合中的真实占比, 长尾 = (stock_pos - top10_cov) × bench
    """
    top10 = holding.top10()
    if not top10:
        return None

    # 股票总仓位 (兜底 0.95)
    stock_pos = holding.stock_position_pct / 100.0 if holding.stock_position_pct else 0.95
    top10_cov = min(sum(p.weight_pct for p in top10) / 100.0, stock_pos)

    # top10 部分: 各股票按"占净值比例"加权
    top10_contrib = 0.0
    for p in top10:
        r = quotes.get(p.code, 0.0)
        top10_contrib += (p.weight_pct / 100.0) * r

    # 长尾: 用 benchmark 代理
    residual_weight = max(stock_pos - top10_cov, 0.0)
    est_change = top10_contrib + residual_weight * benchmark_return

    estimated_nav = t1_nav * (1 + est_change)
    return NAVEstimate(
        fund_code=holding.fund_code, fund_name=holding.fund_name,
        today=today, t1_date=t1_date, t1_nav=t1_nav,
        estimated_nav=estimated_nav,
        estimated_change_pct=est_change,
        method=f"v_active_top10_resid_{benchmark_key}",
        benchmark=benchmark_key,
    )
