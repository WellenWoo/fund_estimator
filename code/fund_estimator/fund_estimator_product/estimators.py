"""商品/商品期货基金估值算法实现（5 种）。

与 ``fund_estimator.estimators.holdings_based`` 对比：
- 持仓还原 / 指数代理假设"能拿到每日指数日线或成分股行情"；
- 商品 LOF 没有指数，且**没有可公开获取的品种期货历史 K 线**（SHFE
  历史 K 线公开接口已下线 / 受限），所以本模块的算法设计为：

  1) **以基金 T-1 官方 NAV 涨跌幅**作为"已知输入"——
     这在盘中是可以拿到的（基金净值每日 21:00 公布，下一交易日 9:30
     已知 T-1 净值和 T-1 涨跌）。商品 LOF 的 NAV 涨跌 ≈ 品种期货涨跌
     （fund_estimator_product.commodity_map.CommodityInfo.beta=1.0 假设），
     因此这是一个有效的代理。

  2) **以 SHFE 品种期货实时价**（hq.sinajs.cn）作为"实时输入"——
     仅在「实时盘中」场景使用，因为 SHFE 期货历史 K 线不可访问。

5 种算法：

+-------------+----------------------------------------------------+
| v_proxy     | T 涨跌% = T-1 涨跌%                                 |
|             | （动量代理，商品有趋势时的有效基线）                 |
+-------------+----------------------------------------------------+
| v_random    | T 涨跌% = 0                                         |
|             | ⭐ （无偏随机游走，理论最优无信息先验）             |
+-------------+----------------------------------------------------+
| v_blend     | T 涨跌% = 0.3 × T-1 + 0.7 × 0 = 0.3 × T-1          |
|             | （保守混合：只取 30% 动量）                         |
+-------------+----------------------------------------------------+
| v_decay     | T 涨跌% = 0.5 × T-1                                |
|             | （半衰减代理，兼顾动量与反转）                      |
+-------------+----------------------------------------------------+
| v_futures   | T 涨跌% = (期货今价 - T-1 收盘) / T-1 收盘          |
|             | （仅实时盘中：直接从 SHFE 主连实时价计算）          |
+-------------+----------------------------------------------------+

注：所有算法最终都遵循 README §4 / ITERATIONS §2 的统一公式： ::

    估算 NAV(T) = T-1 NAV × (1 + 估算涨跌% / 100)

并支持 optional 的 ``fee_drag_pp``（每日费率拖累 pp），用于
模拟「按 0.65%/年化折算 0.018 pp/天」对结果的影响。
"""

from __future__ import annotations

from typing import Optional

from ..core.models import NAVEstimate


# --------------------------------------------------------------------------- #
# 算法注册表
# --------------------------------------------------------------------------- #
DEFAULT_METHOD = "v_random"
"""默认算法：无偏随机游走。理论意义：商品期货价格近似鞅时，
T 日最优预测是 0 涨跌，对应的估算 NAV = T-1 NAV。"""

METHODS = [
    "v_proxy",
    "v_random",
    "v_blend",
    "v_decay",
    "v_futures",
]

METHOD_LABELS = {
    "v_proxy": "T-1 涨跌%代理（动量）",
    "v_random": "随机游走 (T 涨跌%=0) ⭐",
    "v_blend": "0.3×动量 + 0.7×0（保守混合）",
    "v_decay": "0.5×动量（半衰减）",
    "v_futures": "SHFE 期货实时价代理",
}


# --------------------------------------------------------------------------- #
# 工具：构造 NAVEstimate
# --------------------------------------------------------------------------- #
def _make_estimate(
    fund_code: str,
    today: str,
    t1_date: str,
    t1_nav: float,
    change_pct: float,
    method: str,
    detail: dict,
) -> NAVEstimate:
    est_nav = t1_nav * (1.0 + change_pct / 100.0)
    return NAVEstimate(
        fund_code=fund_code,
        today=today,
        t1_date=t1_date,
        t1_nav=round(t1_nav, 6),
        estimated_nav=round(est_nav, 6),
        estimated_change_pct=round(change_pct, 4),
        method=method,
        detail=detail,
    )


# --------------------------------------------------------------------------- #
# 统一入口
# --------------------------------------------------------------------------- #
def estimate(
    method: str,
    *,
    fund_code: str,
    today: str,
    t1_date: str,
    t1_nav: float,
    t1_change_pct: Optional[float] = None,
    futures_change_pct: Optional[float] = None,
    beta: float = 1.0,
    fee_drag_pp: float = 0.0,
    blend_momentum: float = 0.3,
    decay_factor: float = 0.5,
) -> NAVEstimate:
    """商品/商品期货基金统一估值入口。

    Parameters
    ----------
    method:
        5 种算法之一。
    t1_change_pct:
        T-1 当日基金官方涨跌（%），由 fetch_nav_history 的 change_pct 字段提供。
        动量类算法（v_proxy / v_blend / v_decay）必需。
    futures_change_pct:
        底层品种期货 T 日实时涨跌（%），仅 v_futures 必需。
        由 SHFE 期货实时行情计算：(现价 - 昨收) / 昨收 × 100。
    beta:
        基金相对品种的 beta 系数（默认 1.0）。
    fee_drag_pp:
        每日费率拖累（pp）。算法会从估算涨跌% 中扣减此项。
    blend_momentum / decay_factor:
        混合/衰减算法的可调参数。
    """
    if method not in METHODS:
        raise ValueError(f"unknown method: {method}. choices={METHODS}")

    # 1. 动量代理：v_proxy
    if method == "v_proxy":
        if t1_change_pct is None:
            raise ValueError("v_proxy requires t1_change_pct (T-1 涨跌%)")
        change = t1_change_pct * beta - fee_drag_pp
        detail = {
            "t1_change_pct": t1_change_pct,
            "beta": beta,
            "fee_drag_pp": fee_drag_pp,
            "note": "T 日涨跌% = T-1 涨跌% × beta − 费率拖累",
        }
        return _make_estimate(fund_code, today, t1_date, t1_nav, change, method, detail)

    # 2. 随机游走：v_random ⭐
    if method == "v_random":
        change = -fee_drag_pp  # 仅扣费率
        detail = {
            "fee_drag_pp": fee_drag_pp,
            "note": "T 日涨跌% = 0 − 费率拖累 (无偏随机游走基线)",
        }
        return _make_estimate(fund_code, today, t1_date, t1_nav, change, method, detail)

    # 3. 保守混合：v_blend
    if method == "v_blend":
        if t1_change_pct is None:
            raise ValueError("v_blend requires t1_change_pct (T-1 涨跌%)")
        change = blend_momentum * t1_change_pct * beta - fee_drag_pp
        detail = {
            "t1_change_pct": t1_change_pct,
            "blend_momentum": blend_momentum,
            "beta": beta,
            "fee_drag_pp": fee_drag_pp,
            "note": f"T 涨跌% = {blend_momentum} × T-1 涨跌% × beta − 费率拖累",
        }
        return _make_estimate(fund_code, today, t1_date, t1_nav, change, method, detail)

    # 4. 半衰减：v_decay
    if method == "v_decay":
        if t1_change_pct is None:
            raise ValueError("v_decay requires t1_change_pct (T-1 涨跌%)")
        change = decay_factor * t1_change_pct * beta - fee_drag_pp
        detail = {
            "t1_change_pct": t1_change_pct,
            "decay_factor": decay_factor,
            "beta": beta,
            "fee_drag_pp": fee_drag_pp,
            "note": f"T 涨跌% = {decay_factor} × T-1 涨跌% × beta − 费率拖累",
        }
        return _make_estimate(fund_code, today, t1_date, t1_nav, change, method, detail)

    # 5. 期货实时：v_futures（仅实时盘中）
    if method == "v_futures":
        if futures_change_pct is None:
            raise ValueError("v_futures requires futures_change_pct (品种期货 T 日涨跌%)")
        change = futures_change_pct * beta - fee_drag_pp
        detail = {
            "futures_change_pct": futures_change_pct,
            "beta": beta,
            "fee_drag_pp": fee_drag_pp,
            "note": "T 涨跌% = 期货实时涨跌% × beta − 费率拖累 (实时盘中)",
        }
        return _make_estimate(fund_code, today, t1_date, t1_nav, change, method, detail)

    raise ValueError(f"unhandled method: {method}")


__all__ = ["DEFAULT_METHOD", "METHODS", "METHOD_LABELS", "estimate"]
