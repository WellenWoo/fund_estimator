"""每日收盘回测：核心实现，专注跑通流程而非花式算法。

运行模式:
    python -m fund_estimator.backtest.run_backtest --method v_top10 --start 2026-04-25 --end 2026-07-06

输出:
- 每个交易日 估算涨跌幅 vs 实际涨跌幅
- 汇总: MAE / RMSE / 最大偏差 / 偏差>阈值 的天数
- 落盘到 .cache/backtest_{fund}_{method}_{start}_{end}.csv
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from fund_estimator.data_sources.cache import CACHE_DIR  # noqa: E402
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
    abs_error_pp: float
    rel_error_pp: float


def pick_quarter(trade_date: date) -> tuple[int, int]:
    """根据交易日选最近的可用季报（Q1=3月, Q2=6月, Q3=9月, Q4=12月）。"""
    candidates = []
    for y in (trade_date.year, trade_date.year - 1):
        for m in (9, 6, 3, 12):
            cutoff_year = y if m <= trade_date.month or y < trade_date.year else y - 1
            try:
                if m == 12:
                    cutoff = date(cutoff_year, 12, 31)
                elif m in (3,):
                    cutoff = date(cutoff_year, 3, 31)
                elif m in (6,):
                    cutoff = date(cutoff_year, 6, 30)
                elif m in (9,):
                    cutoff = date(cutoff_year, 9, 30)
                else:
                    continue
                candidates.append((cutoff_year, m, cutoff))
            except ValueError:
                continue
    candidates = [c for c in candidates if c[2] < trade_date]
    candidates.sort(key=lambda x: x[2], reverse=True)
    if not candidates:
        raise ValueError("no report available")
    return candidates[0][0], candidates[0][1]


# ----- 估计算法 -----

def estimator_v_top10(holdings, prev_close, today_close, prev_nav):
    """用披露的前 10 大持仓 (实际占比) 直接还原。
    这是 paper_tel.md 章节 5.1 主推方案的核心简化版。
    """
    contrib = 0.0
    for h in holdings[:10]:
        code = h["code"]
        if code in prev_close and code in today_close:
            r = (today_close[code] - prev_close[code]) / prev_close[code]
            contrib += h["weight_pct"] * r
    est_change = contrib / 100.0
    return prev_nav * (1 + est_change)


def estimator_v_residual(holdings, prev_close, today_close, prev_nav):
    """v_top10 + 现金拖累修正 (-0.001/天) + 跟踪误差归一化。"""
    base = estimator_v_top10(holdings, prev_close, today_close, prev_nav)
    # 再叠加一个小幅修正：现金拖累 + 跟踪误差残差
    cash_drag_pct = -0.001  # 一天约 0.1 bp
    return base * (1 + cash_drag_pct)


def estimator_v_residual_uncovered(holdings, prev_close, today_close, prev_nav):
    """v_top10 + 现金拖累 + 残差（用 covered 部分平均变化代替 uncovered 部分）。

    逻辑：实际基金股票仓位 (≈95%) 中, top10 占 53.51%, 剩余 ~42% 是其他股票。
    没有这些股票的数据, 用 covered 部分整体涨跌做代理 + 略低于的权重。
    """
    covered_change_total = 0.0
    covered_w = 0.0
    for h in holdings[:10]:
        code = h["code"]
        if code in prev_close and code in today_close:
            r = (today_close[code] - prev_close[code]) / prev_close[code]
            covered_change_total += h["weight_pct"] * r
            covered_w += h["weight_pct"]

    if covered_w == 0:
        return prev_nav
    avg_covered_change = (covered_change_total / covered_w) if covered_w > 0 else 0

    # 假设 total stock ≈ 95%, top10 already covers covered_w %
    stock_position = 95.0
    uncovered_w = max(stock_position - covered_w, 0.0)

    # uncovered 用 平均 + 一点点方差 (经验: alpha 0.85 因为指数基金个股集中)
    contrib = covered_change_total + uncovered_w * avg_covered_change * 0.85
    est_change = contrib / 100.0
    est_change -= 0.001  # cash drag
    return prev_nav * (1 + est_change)


ESTIMATORS = {
    "v_top10": estimator_v_top10,
    "v_residual": estimator_v_residual,
    "v_residual_uncovered": estimator_v_residual_uncovered,
}


def run_backtest(
    fund_code: str,
    start: date,
    end: date,
    method: str = "v_top10",
    topline: int = 10,
) -> list[DayResult]:
    if method not in ESTIMATORS:
        raise ValueError(f"unknown method: {method}")
    estimator = ESTIMATORS[method]

    # 1) 历史 NAV
    rows = fetch_history(fund_code, start=start - timedelta(days=2), end=end)
    if len(rows) < 2:
        raise SystemExit("not enough NAV rows")

    # 2) 缓存 持仓 与 K 线
    cache_hold: dict[tuple[int, int], list[dict]] = {}
    cache_kline: dict[str, list[dict]] = {}

    def get_holdings(d: date) -> list[dict]:
        y, m = pick_quarter(d)
        key = (y, m)
        if key not in cache_hold:
            try:
                _, hs = fetch_holdings(fund_code, y, m, topline=topline)
                cache_hold[key] = hs[:topline]
            except Exception as e:
                print(f"[warn] holdings fetch failed {key}: {e}", flush=True)
                cache_hold[key] = []
        return cache_hold[key]

    def get_klines(symbol: str) -> list[dict]:
        if symbol not in cache_kline:
            try:
                cache_kline[symbol] = fetch_kline(symbol, 252)
            except Exception as e:
                print(f"[warn] kline fetch failed {symbol}: {e}", flush=True)
                cache_kline[symbol] = []
        return cache_kline[symbol]

    def close_on(symbol: str, d: date) -> float | None:
        k = get_klines(symbol)
        for row in k:
            if row["date"] == d.isoformat():
                try:
                    return float(row["close"])
                except (TypeError, ValueError):
                    return None
        return None

    out: list[DayResult] = []
    for i in range(1, len(rows)):
        prev = rows[i - 1]
        today = rows[i]
        if today["date"] < start or today["date"] > end:
            continue
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
        actual = today["change_pct"]
        abs_err = abs(est_change - actual)
        out.append(
            DayResult(
                trade_date=today["date"],
                estimated_change_pct=round(est_change, 4),
                actual_change_pct=actual,
                abs_error_pp=round(abs_err, 4),
                rel_error_pp=round(est_change - actual, 4),
            )
        )
    return out


def summarize(rs: list[DayResult], threshold_pp: float = 0.5) -> dict:
    if not rs:
        return {"n": 0}
    abs_errs = [r.abs_error_pp for r in rs]
    signed = [r.rel_error_pp for r in rs]
    days_over = sum(1 for e in abs_errs if e > threshold_pp)
    return {
        "n": len(rs),
        "MAE_pp": round(statistics.mean(abs_errs), 4),
        "RMSE_pp": round(statistics.sqrt(statistics.fmean(e * e for e in signed)), 4),
        "MEAN_pp": round(statistics.mean(signed), 4),
        "MAX_pp": round(max(abs_errs), 4),
        "MEDIAN_pp": round(statistics.median(abs_errs), 4),
        f"days_over_{threshold_pp}pp": days_over,
        "over_threshold_ratio": round(days_over / len(rs), 4),
    }


def write_csv(rs: list[DayResult], fund: str, method: str, start: date, end: date) -> Path:
    p = CACHE_DIR / f"backtest_{fund}_{method}_{start.isoformat()}_{end.isoformat()}.csv"
    with p.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["date", "estimated_pct", "actual_pct", "abs_error_pp", "rel_error_pp"])
        for r in rs:
            writer.writerow(
                [r.trade_date.isoformat(), r.estimated_change_pct, r.actual_change_pct, r.abs_error_pp, r.rel_error_pp]
            )
    return p


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--fund-code", default="160223")
    p.add_argument("--start", default="2026-04-25")
    p.add_argument("--end", default="2026-07-06")
    p.add_argument("--method", default="v_top10", choices=list(ESTIMATORS.keys()))
    p.add_argument("--threshold", type=float, default=0.5)
    p.add_argument("--topline", type=int, default=10)
    args = p.parse_args()

    start = date.fromisoformat(args.start)
    end = date.fromisoformat(args.end)
    rs = run_backtest(args.fund_code, start, end, args.method, topline=args.topline)
    summary = summarize(rs, args.threshold)
    print(f"=== 基金 {args.fund_code} 方法 {args.method}  回测 {start}~{end} ===")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print("\n每日明细:")
    print(f"{'date':<12} {'est_pct':>10} {'act_pct':>10} {'abs_err':>10}")
    for r in rs:
        flag = "!" if r.abs_error_pp > args.threshold else " "
        print(f"  {r.trade_date.isoformat()}  {r.estimated_change_pct:+8.3f}%  {r.actual_change_pct:+8.3f}%  {r.abs_error_pp:>8.3f} {flag}")
    out_path = write_csv(rs, args.fund_code, args.method, start, end)
    print(f"\n落盘 → {out_path}")
