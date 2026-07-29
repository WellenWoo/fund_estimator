"""债基实时估值（盘中）模块。

场景
====
盘中 9:30~15:00：
- 已知：T-1 21:00 公布的官方 NAV 和 change_pct（直接用 NAV 序列）
- 未知：T 日收盘 NAV（21:00 后才有）
- 已知/可拉：主代理债券指数（sh000061）的盘中实时价 → 当日涨跌幅

实现要点
========
1. 复用 ``fund_estimator.data_sources.sina.realtime`` 拉代理指数实时价；
2. 若实时接口拉不到（盘前/收盘后），fallback 到 T-1 涨跌% 代理（v_bond_t1_persist）；
3. 返回结构对齐 ``fund_estimator_index_agent.estimate_realtime``，便于上层 GUI 集成。
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timedelta
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

from .bond_map import get_bond_info_for_fund  # noqa: E402
from .estimators import estimate, DEFAULT_METHOD, METHODS  # noqa: E402
from .backtest import _shift_date, _prev_trading_day  # noqa: E402


def _fetch_index_change_pct(symbol: str) -> Optional[float]:
    """从新浪 hq 拉单只指数的实时涨跌幅（%）。失败返回 None。"""
    try:
        quotes = fetch_realtime([symbol])
    except RuntimeError:
        return None
    q = quotes.get(symbol)
    if not q or q.prev_close <= 0 or q.price <= 0:
        return None
    return round((q.price - q.prev_close) / q.prev_close * 100.0, 4)


def estimate_bond_realtime(
    fund_code: str,
    trade_date: str,
    method: Optional[str] = None,
    *,
    force: bool = False,
) -> dict:
    """债基实时盘中估值。

    Parameters
    ----------
    fund_code : str
        6 位债基代码（必须在 BOND_MAP 中）。
    trade_date : str
        估值目标日（YYYY-MM-DD）。
    method : str, optional
        算法标识；None = 用 DEFAULT_METHOD。
    force : bool
        是否强制重拉数据。

    Returns
    -------
    dict
        与 ``fund_estimator_index_agent.estimate_realtime`` 同结构的 JSON dict。
    """
    bond_info = get_bond_info_for_fund(fund_code)
    if bond_info is None:
        return {
            "success": False,
            "fund_code": fund_code,
            "error": f"基金 {fund_code} 不在 BOND_MAP 中，请先在 bond_map.py 注册。",
        }

    method = method or DEFAULT_METHOD
    cache = CsvCache()

    # 1) 取 T-1 官方 NAV 和 T-1 change_pct
    try:
        trade_dt = datetime.strptime(trade_date, "%Y-%m-%d")
        start_date = (trade_dt - timedelta(days=60)).strftime("%Y-%m-%d")
    except ValueError:
        start_date = ""
    nav_rows = fetch_nav_history(fund_code, start_date, trade_date, cache=cache, force=force)
    nav_rows = sorted(nav_rows, key=lambda r: r["date"])
    nav_map = {r["date"]: float(r["nav"]) for r in nav_rows}

    # T 日若有官方 NAV（盘后 21:00 后），使用；否则用最新 NAV 当 T-1
    if trade_date in nav_map:
        t1 = _prev_trading_day([r["date"] for r in nav_rows], trade_date)
        if not t1:
            return {"success": False, "error": f"{trade_date} 无 T-1 交易日"}
        t1_nav = nav_map[t1]
        today_official_nav = nav_map[trade_date]
    else:
        latest = max(nav_map.keys()) if nav_map else None
        if not latest:
            return {"success": False, "error": "无历史 NAV 数据"}
        t1 = latest
        t1_nav = nav_map[t1]
        today_official_nav = None

    t1_change = 0.0
    for r in nav_rows:
        if r["date"] == t1:
            try:
                t1_change = float(r.get("change_pct", 0) or 0)
            except (TypeError, ValueError):
                t1_change = 0.0
            break

    # 2) 拉主代理指数实时价
    primary_symbol = bond_info.primary_index[0]
    idx_change_realtime = _fetch_index_change_pct(primary_symbol)
    if idx_change_realtime is None:
        # fallback：尝试 sina K 线（盘中通常能取到当日）
        try:
            from fund_estimator.data_sources.sina.history import fetch_kline
            kl = fetch_kline(primary_symbol, datalen=5, cache=cache, force=False)
            if kl and len(kl) >= 2:
                last = kl[-1]
                prev = kl[-2]
                if prev.get("close", 0) > 0:
                    idx_change_realtime = round(
                        (last["close"] - prev["close"]) / prev["close"] * 100.0, 4
                    )
        except RuntimeError:
            pass

    idx_change_used = idx_change_realtime if idx_change_realtime is not None else 0.0
    idx_source = "realtime(hq)" if idx_change_realtime is not None else "fallback=0"

    # 3) 调算法
    est = estimate(
        method,
        fund_code=fund_code,
        today=trade_date,
        t1_date=t1,
        t1_nav=t1_nav,
        t1_change_pct=t1_change,
        bond_index_change_pct=idx_change_used,
        beta=bond_info.beta,
        fee_drag_pp=bond_info.fee_drag_pp,
        detail={
            "primary_index": primary_symbol,
            "primary_index_change_pct": idx_change_used,
            "primary_index_source": idx_source,
            "t1_change_pct": t1_change,
        },
    )

    result = {
        "success": True,
        "fund_code": fund_code,
        "fund_name": bond_info.fund_name,
        "fund_subtype": bond_info.fund_subtype,
        "trade_date": trade_date,
        "t1_date": t1,
        "t1_nav": t1_nav,
        "estimated_nav": est.estimated_nav,
        "estimated_change_pct": est.estimated_change_pct,
        "method": method,
        "method_reason": f"债基主推：{METHODS and bond_info.primary_index[1]} 代理（{primary_symbol}）",
        "primary_index": {
            "symbol": primary_symbol,
            "name": bond_info.primary_index[1],
            "change_pct": idx_change_used,
            "source": idx_source,
        },
        "bond_info": bond_info.to_dict(),
    }

    # 4) 对比官方 NAV
    if today_official_nav is not None and t1_nav > 0:
        result["official_nav"] = today_official_nav
        result["official_change_pct"] = (today_official_nav - t1_nav) / t1_nav * 100
        result["abs_error"] = round(est.estimated_nav - today_official_nav, 6)
        est_pct = (est.estimated_nav - t1_nav) / t1_nav * 100
        off_pct = (today_official_nav - t1_nav) / t1_nav * 100
        result["error_pp"] = round(est_pct - off_pct, 4)
        result["over_threshold"] = abs(result["error_pp"]) > THRESHOLD_PP

    return result


def print_result(result: dict) -> None:
    """格式化输出债基估值结果。"""
    if not result.get("success"):
        print(f"\n[ERROR] {result.get('error', 'Unknown error')}")
        return

    print("\n" + "=" * 60)
    print(f"  Bond Fund Valuation -- {result['fund_code']}")
    print("=" * 60)
    print(f"  Name:        {result.get('fund_name', '')}")
    print(f"  Subtype:     {result.get('fund_subtype', '')}")
    print(f"  Method:      {result['method']}")
    print(f"  T-1 Date:    {result['t1_date']}")
    print(f"  T-1 NAV:     {result['t1_nav']:.4f}")
    print(f"  Est NAV:     {result['estimated_nav']:.4f}")
    print(f"  Est Change:  {result['estimated_change_pct']:+.4f}%")
    pi = result.get("primary_index", {})
    print(f"  Index:       {pi.get('symbol', '')} ({pi.get('name', '')})")
    print(f"  Index Chg:   {pi.get('change_pct', 0):+.4f}%  source={pi.get('source', '?')}")
    if "official_nav" in result:
        print(f"  Official NAV:    {result['official_nav']:.4f}")
        print(f"  Official Chg:    {result['official_change_pct']:+.4f}%")
        print(f"  Error (pp):      {result['error_pp']:+.4f}")
        print(f"  Threshold ({THRESHOLD_PP}pp): {'[OVER]' if result.get('over_threshold') else '[PASS]'}")
    else:
        print("  Official NAV not yet published (after 21:00).")
