"""持仓还原 / 参考指数 估值算法（5 种）。

统一接口::

    est = estimate(method, fund_code, today, t1_date, t1_nav, quotes_today,
                   quotes_t1, holdings, index_change_pct=..., ...)

其中行情以「收盘价」形式给出（回测）或「实时价」形式给出（盘中）。
所有算法都遵循 README §4 数据流：

    估算 NAV = T-1 NAV × (1 + 估算涨跌%)

5 种算法（对齐 README §5 / ITERATIONS.md）：

┌────────────────────────┬───────────────────────────────────────────────┐
│ v_top10                │ Σ w_i·r_i / Σ w_i（仅前 10 大，覆盖 ~53%）      │
│ v_index_full           │ 直接用创业板指涨跌%，再扣 cash_drag(0.1%/天基准) │
│ v_index_full_no_cash ⭐│ 直接用创业板指涨跌%，不扣任何费率（主推）        │
│ v_index_blend          │ covered 用持仓还原 + uncovered 用指数代理        │
│ v_residual_uncovered   │ covered 用持仓还原 + uncovered 用 covered 均值   │
└────────────────────────┴───────────────────────────────────────────────┘
"""

from __future__ import annotations

from typing import Optional

from ..core.models import FundHolding, RealtimeQuote, NAVEstimate


CYB_INDEX = "sz399006"   # 创业板指
DEFAULT_METHOD = "v_index_full_no_cash"

# cash_drag：ITERATIONS.md Iteration 1 用 -0.001/天（≈0.36% 年化）
CASH_DRAG_DAILY = 0.001   # 0.1%/天（作为「含 cash_drag」方案的扣减项）

METHODS = [
    "v_top10",
    "v_index_full",
    "v_index_full_no_cash",
    "v_index_blend",
    "v_residual_uncovered",
]

METHOD_LABELS = {
    "v_top10": "持仓还原 top10",
    "v_index_full": "创业板指全代理 (含 cash_drag)",
    "v_index_full_no_cash": "创业板指全代理 (无 cash_drag) ⭐",
    "v_index_blend": "top10 + 创业板指混合",
    "v_residual_uncovered": "top10 + uncovered 代理",
}


def _weighted_holdings_return(
    holdings: list[FundHolding],
    quotes_today: dict[str, RealtimeQuote],
    quotes_t1: dict[str, RealtimeQuote],
) -> tuple[float, float]:
    """按持仓权重加权成分股涨跌幅。

    Returns
    -------
    (weighted_return_pct, covered_weight)
        weighted_return_pct: Σ w_i·r_i（未归一化，单位%）
        covered_weight:      Σ w_i（0~1）
    """
    total_w = 0.0
    weighted = 0.0
    for h in holdings:
        code = h.secid
        qt = quotes_today.get(code)
        q1 = quotes_t1.get(code)
        if not qt or qt.price <= 0:
            continue
        # T-1 收盘价优先用独立的 t1 行情；否则用今日行情里的 prev_close
        prev = None
        if q1 and q1.price > 0:
            prev = q1.price
        elif qt.prev_close > 0:
            prev = qt.prev_close
        if not prev or prev <= 0:
            continue
        r = (qt.price - prev) / prev * 100.0
        w = h.weight
        weighted += w * r
        total_w += w
    return weighted, total_w


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


def estimate(
    method: str,
    *,
    fund_code: str,
    today: str,
    t1_date: str,
    t1_nav: float,
    index_change_pct: Optional[float] = None,
    holdings: Optional[list[FundHolding]] = None,
    quotes_today: Optional[dict[str, RealtimeQuote]] = None,
    quotes_t1: Optional[dict[str, RealtimeQuote]] = None,
    stock_position: float = 0.95,
) -> NAVEstimate:
    """统一估值入口。

    Parameters
    ----------
    method:
        5 种算法之一。
    index_change_pct:
        创业板指当日涨跌幅（%）。index 系算法必需。
    holdings / quotes_today / quotes_t1:
        持仓还原类算法必需。
    stock_position:
        股票总仓位（0~1），默认 0.95（LOF 160223 股票 ≥85%，实际近满仓）。
    """
    holdings = holdings or []
    quotes_today = quotes_today or {}
    quotes_t1 = quotes_t1 or {}

    if method not in METHODS:
        raise ValueError(f"unknown method: {method}. choices={METHODS}")

    # ---- 1. 纯持仓还原（前 10 大） --------------------------------------- #
    if method == "v_top10":
        weighted, cov_w = _weighted_holdings_return(holdings, quotes_today, quotes_t1)
        # 只用 covered 部分的加权收益（忽略未覆盖长尾 → 系统性低估）
        change = weighted  # 直接用 Σ w_i·r_i，未覆盖部分视为 0 变动
        detail = {"weighted_return": weighted, "covered_weight": cov_w}
        return _make_estimate(fund_code, today, t1_date, t1_nav, change, method, detail)

    # ---- 2. 创业板指全代理（含 cash_drag） ------------------------------- #
    if method == "v_index_full":
        if index_change_pct is None:
            raise ValueError("v_index_full requires index_change_pct")
        # 净值涨跌 = 指数涨跌 - 现金拖累（每天固定扣减）
        change = index_change_pct - CASH_DRAG_DAILY * 100.0
        detail = {"index_change_pct": index_change_pct, "cash_drag_pct": CASH_DRAG_DAILY * 100.0}
        return _make_estimate(fund_code, today, t1_date, t1_nav, change, method, detail)

    # ---- 3. 创业板指全代理（无 cash_drag）⭐ 主推 ------------------------ #
    if method == "v_index_full_no_cash":
        if index_change_pct is None:
            raise ValueError("v_index_full_no_cash requires index_change_pct")
        change = index_change_pct
        detail = {"index_change_pct": index_change_pct}
        return _make_estimate(fund_code, today, t1_date, t1_nav, change, method, detail)

    # ---- 4. top10 + 创业板指混合 ----------------------------------------- #
    if method == "v_index_blend":
        if index_change_pct is None:
            raise ValueError("v_index_blend requires index_change_pct")
        weighted, cov_w = _weighted_holdings_return(holdings, quotes_today, quotes_t1)
        # covered 用真实加权，uncovered（到 stock_position）用指数代理
        uncov_w = max(0.0, stock_position - cov_w)
        change = weighted + uncov_w * index_change_pct
        detail = {
            "covered_return": weighted,
            "covered_weight": cov_w,
            "uncovered_weight": uncov_w,
            "index_change_pct": index_change_pct,
        }
        return _make_estimate(fund_code, today, t1_date, t1_nav, change, method, detail)

    # ---- 5. top10 + uncovered 用 covered 均值代理 ------------------------ #
    if method == "v_residual_uncovered":
        weighted, cov_w = _weighted_holdings_return(holdings, quotes_today, quotes_t1)
        avg_r = (weighted / cov_w) if cov_w > 0 else 0.0
        uncov_w = max(0.0, stock_position - cov_w)
        change = weighted + uncov_w * avg_r
        detail = {
            "covered_return": weighted,
            "covered_weight": cov_w,
            "avg_covered_return": avg_r,
            "uncovered_weight": uncov_w,
        }
        return _make_estimate(fund_code, today, t1_date, t1_nav, change, method, detail)

    raise ValueError(f"unhandled method: {method}")
