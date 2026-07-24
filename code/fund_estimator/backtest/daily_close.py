"""每日收盘回测:用历史 K 线 + 历史 NAV + 季度披露持仓,估算每个交易日收盘净值,与官方 NAV 对比。

数据准备:
- 持仓:基金季报披露的前 10 大持仓(占净值比例),来自东方财富基金档案
- 行情:每只持仓股票当日的日内收盘价(新浪历史 K 线)
- 基金官方 NAV:东方财富 lsjz API

回测范围:
- 持仓披露日之后,到下一个调仓日之间
- 默认:[disclose_date_of(Q1),2026-07-06]
- 持仓假设:在两个调仓日之间持仓不变(LOF 这种被动跟踪指数,调仓往往较频繁但保留权重比例稳定)

输出:
- 每个交易日的 (日期, 估算涨跌幅, 实际涨跌幅, 相对误差)
- 汇总:MAE / RMSE / 最大偏差 / 偏差 > 阈值的天数
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from fund_estimator.data_sources.eastmoney.holdings_full import (  # noqa: E402
    fetch_holdings,
)
from fund_estimator.data_sources.eastmoney.nav_history import (  # noqa: E402
    fetch_history,
)
from fund_estimator.data_sources.sina.history import fetch_kline  # noqa: E402


@dataclass
class DayResult:
    trade_date: date
    estimated_change_pct: float
    actual_change_pct: float
    rel_error_pct: float  # 估算涨跌幅 - 实际涨跌幅 (单位:百分点 pp)


def _pick_quarter_for(trade_date: date) -> tuple[int, int]:
    """根据 trade_date 选最近的可用季报(假设披露日落后 30-45 个自然日)。"""
    # 简化:选 trade_date 之前最近的 (year, month) 组合
    candidates = []
    for y, m in [(trade_date.year, 3), (trade_date.year - 1, 9), (trade_date.year - 1, 6), (trade_date.year - 1, 3)]:
        # m 是报告截止月
        cutoff = date(y, m, 30) if m in (6, 9) else date(y, m, 31)
        if cutoff < trade_date:
            candidates.append((y, m, cutoff))
    candidates.sort(key=lambda x: x[2], reverse=True)
    if not candidates:
        raise ValueError("no report available")
    y, m, _ = candidates[0]
    return y, m


def backtest(
    fund_code: str,
    start: date,
    end: date,
    estimator,  # callable(holdings, prev_close_by_code, today_close_by_code, prev_nav) -> estimated_nav
) -> list[DayResult]:
    """跑历史回测。

    estimator signature:
        estimated_nav = estimator(
            holdings: list[dict],           # [{code, weight_pct, name}, ...]
            prev_close_by_code: dict,        # {code: float}
            today_close_by_code: dict,       # {code: float}
            prev_official_nav: float,
        )
    """
    # 1) 拉历史 NAV
    rows = fetch_history(fund_code, start=start, end=end)
    if len(rows) < 2:
        raise SystemExit("not enough history rows")

    # 2) 按 trade_date 选最近季报
    cache_holdings: dict[tuple[int, int], list[dict]] = {}
    cache_kline: dict[str, list[dict]] = {}

    def get_holdings(d: date) -> list[dict]:
        y, m = _pick_quarter_for(d)
        key = (y, m)
        if key not in cache_holdings:
            try:
                _, hs = fetch_holdings(fund_code, y, m, topline=20)
                cache_holdings[key] = hs
            except Exception as e:
                print(f"[warn] holdings {y}-{m}: {e}")
                cache_holdings[key] = []
        return cache_holdings[key]

    def get_klines(symbol: str) -> list[dict]:
        if symbol not in cache_kline:
            import time
            rows: list[dict] = []
            last: Exception | None = None
            for datalen in (252, 180, 120, 60):
                try:
                    rows = fetch_kline(symbol, datalen)
                    break
                except Exception as e:
                    last = e
                    time.sleep(1.5 + datalen * 0.005)
            if not rows:
                # print and use empty as cache (so the rest of the loop skips this symbol)
                print(f"[warn] kline fetch failed for {symbol}: {last}", flush=True)
                cache_kline[symbol] = []
            else:
                cache_kline[symbol] = rows
            time.sleep(0.2)
        return cache_kline[symbol] 

    def close_on(symbol: str, d: date) -> Optional[float]:
        k = get_klines(symbol)
        for row in k:
            if row["date"] == d.isoformat():
                return row["close"]
        return None

    out: list[DayResult] = []
    for i in range(1, len(rows)):
        prev = rows[i - 1]
        today = rows[i]
        if today["nav"] is None or prev["nav"] is None or today["change_pct"] is None:
            continue

        holdings = get_holdings(today["date"])
        if not holdings:
            continue

        prev_close = {}
        today_close = {}
        for h in holdings:
            code = h["code"]
            sym = f"sz{code}" if code.startswith("3") else f"sh{code}"
            p1 = close_on(sym, prev["date"])
            p2 = close_on(sym, today["date"])
            if p1 and p2:
                prev_close[code] = p1
                today_close[code] = p2

        if not prev_close or not today_close:
            continue

        est_nav = estimator(holdings, prev_close, today_close, prev["nav"])
        est_change = (est_nav - prev["nav"]) / prev["nav"] * 100.0
        rel_err = est_change - today["change_pct"]

        out.append(
            DayResult(
                trade_date=today["date"],
                estimated_change_pct=round(est_change, 4),
                actual_change_pct=today["change_pct"],
                rel_error_pct=round(rel_err, 4),
            )
        )
    return out


def summarize(rs: list[DayResult], threshold_pp: float = 0.5) -> dict:
    if not rs:
        return {"n": 0}
    errs = [r.rel_error_pct for r in rs]
    abs_errs = [abs(e) for e in errs]
    days_over = sum(1 for e in abs_errs if e > threshold_pp)
    return {
        "n": len(rs),
        "MAE_pp": round(statistics.mean(abs_errs), 4),
        "RMSE_pp": round(statistics.sqrt(statistics.fmean(e * e for e in errs)), 4),
        "MEAN_pp": round(statistics.mean(errs), 4),
        "MAX_pp": round(max(abs_errs), 4),
        "MEDIAN_pp": round(statistics.median(abs_errs), 4),
        f"days_over_{threshold_pp}pp": days_over,
        "over_threshold_ratio": round(days_over / len(rs), 4),
    }


# ----- 内置 estimators -----

def estimator_full_holdings_v1(holdings, prev_close, today_close, prev_nav):
    """v1: 用披露的前 N 持仓的实际占比(其余当 0)。"""
    total_w = 0.0
    contrib = 0.0
    for h in holdings:
        code = h["code"]
        if code in prev_close and code in today_close:
            w = h["weight_pct"]
            r = (today_close[code] - prev_close[code]) / prev_close[code]
            contrib += w * r
            total_w += w
    est_change = contrib / 100.0  # 因为 weight_pct 是百分数
    return prev_nav * (1 + est_change)


def estimator_full_holdings_v2(holdings, prev_close, today_close, prev_nav):
    """v2: 把未披露个股归一化为股票仓位基金 (≈95%) 减去已披露占的比例。

    思路: 实际基金股票仓位 (e.g., 95%) 中, 已知 top10 占 53.51%, 剩余 41.49%
    也是股票仓位, 用创业板指 399006 这一宽基指数做代理.
    """
    # 我们这里简化为:未覆盖部分按所有已覆盖部分的平均涨跌计入
    covered_codes = [h["code"] for h in holdings if h["code"] in prev_close and h["code"] in today_close]
    if not covered_codes:
        return prev_nav
    avg_change = sum(
        (today_close[c] - prev_close[c]) / prev_close[c] for c in covered_codes
    ) / len(covered_codes)
    # 把"未覆盖部分"按股票仓位 (95%) - 已覆盖 (53%) = 42% 占位
    covered_w = sum(h["weight_pct"] for h in holdings if h["code"] in covered_codes)
    stock_position = 95.0  # 来自 pingzhongdata 的 Data_fundSharesPositions
    uncovered_w = max(stock_position - covered_w, 0.0)
    covered_contrib = sum(
        h["weight_pct"] * (today_close[h["code"]] - prev_close[h["code"]]) / prev_close[h["code"]]
        for h in holdings if h["code"] in covered_codes
    )
    uncovered_contrib = uncovered_w * avg_change
    est_change = (covered_contrib + uncovered_contrib) / 100.0
    # 加上现金拖累 ≈ -0.001 (一天)
    est_change -= 0.001
    return prev_nav * (1 + est_change)


def estimator_top10_actual(holdings, prev_close, today_close, prev_nav):
    """v3: 只用真实披露的 前 10 大持仓, 直接忽略其他持仓.

    这是最贴近现实的做法 (因为我们没有覆盖到 100 只成分股).
    """
    covered_contrib = 0.0
    covered_w = 0.0
    for h in holdings[:10]:
        code = h["code"]
        if code in prev_close and code in today_close:
            r = (today_close[code] - prev_close[code]) / prev_close[code]
            covered_contrib += h["weight_pct"] * r
            covered_w += h["weight_pct"]
    if covered_w == 0:
        return prev_nav
    est_change = covered_contrib / 100.0
    return prev_nav * (1 + est_change)


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--fund-code", default="160223")
    p.add_argument("--start", default="2026-04-25")
    p.add_argument("--end", default="2026-07-06")
    p.add_argument("--method", default="v1", choices=["v1", "v2", "v3"])
    p.add_argument("--threshold", type=float, default=0.5, help="阈值 (pp)")
    args = p.parse_args()

    start = date.fromisoformat(args.start)
    end = date.fromisoformat(args.end)
    estimators = {
        "v1": estimator_full_holdings_v1,
        "v2": estimator_full_holdings_v2,
        "v3": estimator_top10_actual,
    }
    rs = backtest(args.fund_code, start, end, estimators[args.method])
    summary = summarize(rs, args.threshold)
    print(f"=== 基金 {args.fund_code} 方法 {args.method}  回测 {start}~{end} ===")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print("\n每日明细:")
    print(f"{'date':<12} {'est_pct':>10} {'act_pct':>10} {'err_pp':>10}")
    for r in rs:
        flag = "!" if abs(r.rel_error_pct) > args.threshold else " "
        print(f"{r.trade_date.isoformat()}  {r.estimated_change_pct:+8.3f}%  {r.actual_change_pct:+8.3f}%  {r.rel_error_pct:+8.3f} {flag}")
