"""商品基金实时估值（盘中）模块。

场景
----
盘中 9:30~15:00：已知 T-1 21:00 公布的官方 NAV / 涨跌%；
  - v_proxy / v_blend / v_decay / v_random 都用 T-1 涨跌% 即可工作
    （不需要联网，零延迟）
  - v_futures 需要 SHFE 期货实时价 → 通过 sina hq.sinajs.cn 抓取

实现要点
--------
1. ``fetch_realtime`` 走 ``fund_estimator.data_sources.sina.realtime``
   （已经支持 SHFE 主连代码 AG0 / AU0 等）。
2. 期货价格字段在新浪接口里是按「股票 32 字段」格式返回：
   ``name, open, prev_close, current, high, low, ...``。
   ``change_pct = (current - prev_close) / prev_close × 100``。
3. 返回结构对齐 ``fund_estimator_index_agent.estimate_realtime``：
   让上层 GUI / Agent 调用代码无差异。
"""

from __future__ import annotations

import os
import sys
from typing import Optional

# --- import 引导 ------------------------------------------------------------ #
_THIS = os.path.dirname(os.path.abspath(__file__))
_CODE_ROOT = os.path.dirname(os.path.dirname(_THIS))   # code/fund_estimator/
if _CODE_ROOT not in sys.path:
    sys.path.insert(0, _CODE_ROOT)

from fund_estimator.core.models import THRESHOLD_PP  # noqa: E402
from fund_estimator.data_sources.cache import CsvCache  # noqa: E402
from fund_estimator.data_sources.eastmoney.nav_history import fetch_nav_history  # noqa: E402
from fund_estimator.data_sources.sina.realtime import fetch_realtime  # noqa: E402
from fund_estimator.fund_estimator_index_agent import _prev_trading_day  # noqa: E402

from .commodity_map import get_commodity_for_fund  # noqa: E402
from .estimators import estimate, DEFAULT_METHOD, METHODS  # noqa: E402


def _fetch_futures_change_pct(symbol: str) -> Optional[float]:
    """从新浪 hq 抓取 SHFE 主连期货实时涨跌%。

    Returns
    -------
    float or None
        期货 T 日实时涨跌幅（%），如 -1.23 表示 -1.23%。
        获取失败返回 None（调用方应 fallback 到 T-1 涨跌% 算法）。
    """
    try:
        quotes = fetch_realtime([symbol])
    except RuntimeError:
        return None
    q = quotes.get(symbol)
    if not q or q.prev_close <= 0 or q.price <= 0:
        return None
    return round((q.price - q.prev_close) / q.prev_close * 100.0, 4)


def estimate_commodity_realtime(
    fund_code: str,
    trade_date: str,
    method: Optional[str] = None,
    *,
    force: bool = False,
) -> dict:
    """商品基金实时盘中估值。

    Parameters
    ----------
    fund_code:
        6 位商品基金代码（如 161226）。
    trade_date:
        估值目标日期 (YYYY-MM-DD)。
    method:
        5 种算法之一；不传则按 DEFAULT_METHOD = "v_random"。
    force:
        强制重取 NAV / 行情（忽略缓存）。

    Returns
    -------
    dict
        与 ``fund_estimator_index_agent.estimate_realtime`` 字段对齐：
        ``success, fund_code, trade_date, t1_date, t1_nav,
        estimated_nav, estimated_change_pct, method, detail,
        commodity, symbol, error, ...``。
    """
    cache = CsvCache()
    commodity = get_commodity_for_fund(fund_code)
    if commodity is None:
        return {
            "success": False,
            "fund_code": fund_code,
            "trade_date": trade_date,
            "error": f"fund {fund_code} not in COMMODITY_MAP (商品基金映射表)",
        }

    method = method or DEFAULT_METHOD
    if method not in METHODS:
        return {
            "success": False,
            "fund_code": fund_code,
            "trade_date": trade_date,
            "error": f"unknown method: {method}. choices={METHODS}",
        }

    # 1. 取历史 NAV 范围（取最近 ~60 个交易日即可拿到 T-1）
    try:
        nav_rows = fetch_nav_history(fund_code, cache=cache, force=force)
    except RuntimeError as exc:
        return {
            "success": False,
            "fund_code": fund_code,
            "trade_date": trade_date,
            "error": f"fetch_nav_history failed: {exc}",
        }

    if not nav_rows:
        return {
            "success": False,
            "fund_code": fund_code,
            "trade_date": trade_date,
            "error": "no NAV history",
        }

    nav_map = {r["date"]: r["nav"] for r in nav_rows}
    tdays = sorted(nav_map.keys())

    # 2. 解析 T-1
    t1 = _prev_trading_day(tdays, trade_date)
    if not t1:
        # 实时盘中可能 trade_date 还没公布 NAV，回退到最新可用交易日作为 T-1
        t1 = tdays[-1]
    t1_nav = nav_map[t1]

    t1_change = None
    for r in nav_rows:
        if r["date"] == t1:
            try:
                t1_change = float(r.get("change_pct") or 0.0)
            except (TypeError, ValueError):
                t1_change = 0.0
            break

    # 3. 仅 v_futures 才联网抓 SHFE 实时价
    futures_change = None
    if method == "v_futures":
        futures_change = _fetch_futures_change_pct(commodity.symbol)

    # 4. 估值
    est = estimate(
        method,
        fund_code=fund_code,
        today=trade_date,
        t1_date=t1,
        t1_nav=t1_nav,
        t1_change_pct=t1_change,
        futures_change_pct=futures_change,
        beta=commodity.beta,
        fee_drag_pp=commodity.fee_drag_pp,
    )

    result = {
        "success": True,
        "fund_code": fund_code,
        "fund_name": commodity.fund_name,
        "commodity": commodity.commodity,
        "symbol": commodity.symbol,
        "trade_date": trade_date,
        "t1_date": t1,
        "t1_nav": est.t1_nav,
        "t1_change_pct": t1_change,
        "estimated_nav": est.estimated_nav,
        "estimated_change_pct": est.estimated_change_pct,
        "method": est.method,
        "detail": est.detail,
    }

    # 5. 如果今天 NAV 已经公布（盘后/晚 21:00 后），对比官方
    if trade_date in nav_map:
        official_nav = nav_map[trade_date]
        result["official_nav"] = official_nav
        if t1_nav > 0:
            result["official_change_pct"] = (official_nav - t1_nav) / t1_nav * 100.0
            err_pp = est.estimated_change_pct - result["official_change_pct"]
            result["abs_error"] = round(est.estimated_nav - official_nav, 6)
            result["error_pp"] = round(err_pp, 4)
            result["over_threshold"] = abs(err_pp) > THRESHOLD_PP

    return result


__all__ = ["estimate_commodity_realtime", "_fetch_futures_change_pct"]
