"""主回测入口 —— 遍历日期区间，对每个交易日做估值并与官方 NAV 对比。

设计（对齐 ITERATIONS.md）：
1. 预取全区间：基金历史 NAV、创业板指日线、（可选）成分股日线。
2. 用 NAV 的日期集合 ∩ 指数交易日 构建 trading_days，非交易日直接跳过
   （修复 Iteration 3 记录的「非交易日 None-float TypeError」bug）。
3. 对每个交易日：
   - T-1 = 上一个有 NAV 的交易日
   - index_change_pct = 指数(today.close / t1.close - 1) × 100
   - 调 estimators.estimate(method, ...)
   - 与官方 NAV(today) 组成 NAVComparison
4. 聚合 MAE / RMSE / MAX / Mean / over_threshold。

本模块既是脚本（python -m / 直接运行），也向 iteration_tracker 暴露 backtest_range。
"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass, field
from typing import Optional

# --- import 引导：确保能 import fund_estimator.* ---------------------------- #
_THIS = os.path.dirname(os.path.abspath(__file__))
_CODE_ROOT = os.path.dirname(os.path.dirname(_THIS))  # code/
if _CODE_ROOT not in sys.path:
    sys.path.insert(0, _CODE_ROOT)

from fund_estimator.core.models import NAVComparison, THRESHOLD_PP  # noqa: E402
from fund_estimator.data_sources.cache import CsvCache  # noqa: E402
from fund_estimator.data_sources.eastmoney.nav_history import fetch_nav_history  # noqa: E402
from fund_estimator.data_sources.eastmoney.holdings_full import fetch_full_holdings  # noqa: E402
from fund_estimator.data_sources.sina.history import fetch_kline  # noqa: E402
from fund_estimator.estimators.holdings_based import estimate, CYB_INDEX, DEFAULT_METHOD, METHODS  # noqa: E402


FUND_CODE = "160223"


# --------------------------------------------------------------------------- #
# 共享输入
# --------------------------------------------------------------------------- #
@dataclass
class CommonInputs:
    """一次回测所需的全部预取数据。"""

    fund_code: str
    nav_rows: list[dict]                 # 升序 [{date, nav, ...}]
    nav_map: dict[str, float]            # date -> nav
    index_close: dict[str, float]        # date -> 创业板指收盘
    trading_days: list[str]              # 有 NAV 的交易日（升序）
    holdings: list = field(default_factory=list)   # 完整持仓（FundHolding）
    stock_quote_close: dict[str, dict[str, float]] = field(default_factory=dict)
    # stock_quote_close[code][date] = close


def load_common_inputs(
    fund_code: str = FUND_CODE,
    start: str = "",
    end: str = "",
    *,
    with_holdings: bool = True,
    with_stocks: bool = False,
    cache: Optional[CsvCache] = None,
    force: bool = False,
) -> CommonInputs:
    """预取回测所需数据。

    with_stocks=True 时才抓成分股日线（持仓还原类算法需要），否则跳过省流量。
    """
    cache = cache or CsvCache()

    nav_rows = fetch_nav_history(fund_code, start, end, cache=cache, force=force)
    nav_map = {r["date"]: r["nav"] for r in nav_rows}

    index_rows = fetch_kline(CYB_INDEX, cache=cache, force=force)
    index_close = {r["date"]: r["close"] for r in index_rows}

    # 交易日 = 有 NAV 且落在区间内
    tdays = [
        r["date"]
        for r in nav_rows
        if (not start or r["date"] >= start) and (not end or r["date"] <= end)
    ]

    holdings = []
    stock_close: dict[str, dict[str, float]] = {}
    if with_holdings:
        full = fetch_full_holdings(fund_code, cache=cache, force=force)
        holdings = full.holdings
        if with_stocks:
            for h in holdings:
                rows = fetch_kline(h.secid, cache=cache, force=force)
                stock_close[h.secid] = {r["date"]: r["close"] for r in rows}

    return CommonInputs(
        fund_code=fund_code,
        nav_rows=nav_rows,
        nav_map=nav_map,
        index_close=index_close,
        trading_days=tdays,
        holdings=holdings,
        stock_quote_close=stock_close,
    )


def _prev_trading_day(tdays: list[str], today: str) -> Optional[str]:
    prev = None
    for d in tdays:
        if d < today:
            prev = d
        elif d == today:
            return prev
        else:
            break
    return prev


def _quotes_from_close(
    inputs: CommonInputs, date: str
) -> dict:
    """把某交易日的成分股收盘价包装成 {code: RealtimeQuote} 供持仓还原算法用。"""
    from fund_estimator.core.models import RealtimeQuote

    out = {}
    for code, series in inputs.stock_quote_close.items():
        px = series.get(date)
        if px is not None:
            out[code] = RealtimeQuote(code=code, price=px)
    return out


def estimate_for_day(
    inputs: CommonInputs,
    today: str,
    method: str,
    realtime: bool = False,
) -> Optional[NAVComparison]:
    """对单个交易日做估值 + 对比。非交易日 / 数据缺失返回 None。

    Parameters
    ----------
    realtime : 实时估值模式。为 True 时，即使 today 不在 nav_map 中
               （当天 NAV 尚未公布），也使用最新可用 NAV 作为 T-1 进行估算。
    """
    t1 = None
    t1_nav = None

    if today not in inputs.nav_map:
        if realtime and inputs.nav_map:
            # 实时估值：当天 NAV 未公布，用最后一个可用交易日作为 T-1
            latest_date = max(inputs.nav_map.keys())
            t1 = latest_date
            t1_nav = inputs.nav_map[t1]
        else:
            return None  # 非交易日（无 NAV）
    else:
        t1 = _prev_trading_day(inputs.trading_days, today)
        if not t1:
            return None
        t1_nav = inputs.nav_map.get(t1)
        if not t1_nav:
            return None

    # 指数涨跌%
    idx_today = inputs.index_close.get(today)
    idx_t1 = inputs.index_close.get(t1)
    index_change_pct = None
    if idx_today and idx_t1 and idx_t1 > 0:
        index_change_pct = (idx_today - idx_t1) / idx_t1 * 100.0
    elif realtime and idx_t1 and idx_t1 > 0:
        # 实时模式：当天指数数据缺失，保留 index_change_pct 为 None
        # 让 estimate_realtime 中的实时指数回退逻辑来处理
        # index_change_pct 保持为 None
        pass

    # index 系算法在缺指数时无法估
    if method in ("v_index_full", "v_index_full_no_cash", "v_index_blend") and index_change_pct is None:
        return None

    quotes_today = _quotes_from_close(inputs, today)
    quotes_t1 = _quotes_from_close(inputs, t1)

    est = estimate(
        method,
        fund_code=inputs.fund_code,
        today=today,
        t1_date=t1,
        t1_nav=t1_nav,
        index_change_pct=index_change_pct,
        holdings=inputs.holdings,
        quotes_today=quotes_today,
        quotes_t1=quotes_t1,
    )

    official_nav = inputs.nav_map.get(today)
    official_change = None
    if official_nav and t1_nav > 0:
        official_change = (official_nav - t1_nav) / t1_nav * 100.0

    return NAVComparison(
        estimate=est,
        official_nav=official_nav,
        official_change_pct=official_change,
    )


# --------------------------------------------------------------------------- #
# 统计
# --------------------------------------------------------------------------- #
@dataclass
class BacktestResult:
    method: str
    start: str
    end: str
    comparisons: list[NAVComparison]

    @property
    def valid(self) -> list[NAVComparison]:
        return [c for c in self.comparisons if c.error_pp is not None]

    def stats(self) -> dict:
        errs = [c.error_pp for c in self.valid]
        n = len(errs)
        if n == 0:
            return {"method": self.method, "n": 0}
        mae = sum(abs(e) for e in errs) / n
        rmse = (sum(e * e for e in errs) / n) ** 0.5
        mean = sum(errs) / n
        mx = max(abs(e) for e in errs)
        over = sum(1 for e in errs if abs(e) > THRESHOLD_PP)
        return {
            "method": self.method,
            "label": None,
            "start": self.start,
            "end": self.end,
            "n": n,
            "mae_pp": round(mae, 4),
            "rmse_pp": round(rmse, 4),
            "mean_pp": round(mean, 4),
            "max_pp": round(mx, 4),
            "over_threshold": over,
            "over_ratio": f"{over}/{n}",
        }


def backtest_range(
    inputs: CommonInputs,
    method: str,
    start: str,
    end: str,
) -> BacktestResult:
    """在 [start, end] 区间内对单一方法回测。"""
    comps: list[NAVComparison] = []
    for today in inputs.trading_days:
        if start and today < start:
            continue
        if end and today > end:
            continue
        c = estimate_for_day(inputs, today, method)
        if c is not None:
            comps.append(c)
    return BacktestResult(method=method, start=start, end=end, comparisons=comps)


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def main(argv: Optional[list[str]] = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
    parser = argparse.ArgumentParser(description="主回测入口（持仓还原 / 指数代理）")
    parser.add_argument("--fund", default=FUND_CODE)
    parser.add_argument("--method", default=DEFAULT_METHOD, choices=METHODS)
    parser.add_argument("--start", default="2026-04-25")
    parser.add_argument("--end", default="2026-07-14")
    parser.add_argument("--force", action="store_true", help="忽略缓存强制重取")
    args = parser.parse_args(argv)

    need_stocks = args.method in ("v_top10", "v_index_blend", "v_residual_uncovered")
    inputs = load_common_inputs(
        args.fund, args.start, args.end,
        with_holdings=True, with_stocks=need_stocks, force=args.force,
    )
    result = backtest_range(inputs, args.method, args.start, args.end)
    stats = result.stats()
    import json
    print(json.dumps(stats, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
