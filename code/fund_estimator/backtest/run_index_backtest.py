"""扩展版回测：含参考指数法 (v_index) 作为对比。

新增方法:
- v_index_chinext: 直接用创业板指 (sz399006) 的涨跌幅代替
- v_index_chinext_pos: 创业板指 + 扣减股票仓位 (95%) + 现金拖累
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
import sys
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from fund_estimator.data_sources.cache import CACHE_DIR  # noqa: E402
from fund_estimator.data_sources.eastmoney.nav_history import (  # noqa: E402
    fetch_history,
)
from fund_estimator.data_sources.sina.history import fetch_kline  # noqa: E402

# 复用 run_backtest 的估算器和 DayResult 等
from fund_estimator.backtest.run_backtest import (  # noqa: E402
    DayResult,
    estimator_v_top10,
    estimator_v_residual,
    estimator_v_residual_uncovered,
    summarize,
    write_csv,
    run_backtest,
)


def estimator_v_index_chinext_full(holdings, prev_close, today_close, prev_nav):
    """v_index_full: 完全用创业板指 (sz399006) 涨跌幅, 扣 1.0% 现金拖累。

    LOF 160223 是完全复制创业板指数的指数基金, 跟踪误差 < 2%,
    所以最简单粗暴的方法：当日 NAV ≈ T-1 NAV × (1 + 创业板指涨跌%)
    - cash_drag(≈0.001/天 = 0.026% 年化, 不对, 大概 -0.001/天 = -0.4%/年, 实际是 -1.5%/年)
    """
    # 注意：这里我们假设调用方会把 sz399006 当成一个"持仓"传进来
    if "INDEX" not in prev_close or "INDEX" not in today_close:
        return prev_nav
    index_change = (today_close["INDEX"] - prev_close["INDEX"]) / prev_close["INDEX"]
    est_change = index_change
    # 加一个小修正: 现金拖累
    est_change -= 0.001
    return prev_nav * (1 + est_change)


def estimator_v_index_chinext_full_no_cash(holdings, prev_close, today_close, prev_nav):
    """v_index_full_no_cash: 不扣现金流扣 (实验性)。

    观察 backtest: v_index_full 上扣了 -0.001/天, 会贡献约 -0.10pp/day 的 bias。
    这个变量不扣, 验证假设。
    """
    if "INDEX" not in prev_close or "INDEX" not in today_close:
        return prev_nav
    index_change = (today_close["INDEX"] - prev_close["INDEX"]) / prev_close["INDEX"]
    return prev_nav * (1 + index_change)


def estimator_v_index_chinext_holdings_plus_index(holdings, prev_close, today_close, prev_nav):
    """v_index_blend: top10 实际占比 + 指数做 uncovered 代理.

    改进 v_residual_uncovered：用真实的创业板指涨跌代替平均涨跌。
    """
    if "INDEX" not in prev_close or "INDEX" not in today_close:
        return estimator_v_residual_uncovered(holdings, prev_close, today_close, prev_nav)
    index_change = (today_close["INDEX"] - prev_close["INDEX"]) / prev_close["INDEX"]

    # 已覆盖部分 (top10)
    covered_change_total = 0.0
    covered_w = 0.0
    for h in holdings[:10]:
        code = h["code"]
        if code in prev_close and code in today_close:
            r = (today_close[code] - prev_close[code]) / prev_close[code]
            covered_change_total += h["weight_pct"] * r
            covered_w += h["weight_pct"]

    # uncovered 用指数涨跌 × (股票仓位 - 已覆盖)
    stock_position = 95.0
    uncovered_w = max(stock_position - covered_w, 0.0)
    contrib = covered_change_total + uncovered_w * index_change
    est_change = contrib / 100.0 - 0.001  # 现金拖累
    return prev_nav * (1 + est_change)


def run_backtest_with_index(
    fund_code: str,
    start: date,
    end: date,
    method: str = "v_index_blend",
    topline: int = 10,
) -> list[DayResult]:
    """带创业板指代理的回测 (在 holdings 列表里追加一个 'INDEX' 哨兵)。"""
    estimators = {
        "v_index_full": estimator_v_index_chinext_full,
        "v_index_full_no_cash": estimator_v_index_chinext_full_no_cash,
        "v_index_blend": estimator_v_index_chinext_holdings_plus_index,
        "v_top10": estimator_v_top10,
        "v_residual": estimator_v_residual,
        "v_residual_uncovered": estimator_v_residual_uncovered,
    }
    if method not in estimators:
        raise ValueError(f"unknown method: {method}")
    estimator = estimators[method]

    rows = fetch_history(fund_code, start=start - timedelta(days=2), end=end)
    if len(rows) < 2:
        raise SystemExit("not enough NAV rows")

    # 拉创业板指 kline
    index_kline = fetch_kline("sz399006", 252)
    index_by_date = {r["date"]: float(r["close"]) for r in index_kline if r.get("close")}

    cache_hold: dict[tuple[int, int], list[dict]] = {}
    cache_kline: dict[str, list[dict]] = {}

    def get_holdings(d: date) -> list[dict]:
        from fund_estimator.data_sources.eastmoney.holdings_full import fetch_holdings
        from fund_estimator.backtest.run_backtest import pick_quarter

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
        if today["date"].isoformat() not in index_by_date:
            continue

        holdings = get_holdings(today["date"])
        if not holdings and "v_index" in method and method != "v_index_full":
            holdings = [{"code": "INDEX", "weight_pct": 0}]  # placeholder
        if method == "v_index_full" and not holdings:
            holdings = []

        prev_close = {"INDEX": index_by_date[prev["date"].isoformat()]}
        today_close = {"INDEX": index_by_date[today["date"].isoformat()]}
        for h in holdings:
            code = h["code"]
            if code == "INDEX":
                continue
            sym = f"sz{code}" if code.startswith("3") else f"sh{code}"
            p1 = close_on(sym, prev["date"])
            p2 = close_on(sym, today["date"])
            if p1 and p2:
                prev_close[code] = p1
                today_close[code] = p2

        est_nav = estimator(holdings, prev_close, today_close, prev["nav"])
        est_change = (est_nav - prev["nav"]) / prev["nav"] * 100.0
        actual = today["change_pct"]
        out.append(
            DayResult(
                trade_date=today["date"],
                estimated_change_pct=round(est_change, 4),
                actual_change_pct=actual,
                abs_error_pp=round(abs(est_change - actual), 4),
                rel_error_pp=round(est_change - actual, 4),
            )
        )
    return out


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--fund-code", default="160223")
    p.add_argument("--start", default="2026-04-25")
    p.add_argument("--end", default="2026-07-06")
    p.add_argument(
        "--method",
        default="v_index_blend",
        choices=[
            "v_top10",
            "v_residual",
            "v_residual_uncovered",
            "v_index_full",
            "v_index_full_no_cash",
            "v_index_blend",
        ],
    )
    p.add_argument("--threshold", type=float, default=0.5)
    p.add_argument("--topline", type=int, default=10)
    args = p.parse_args()

    start = date.fromisoformat(args.start)
    end = date.fromisoformat(args.end)

    # 一些方法需要 holdings, 一些不需要
    if "v_index" in args.method:
        rs = run_backtest_with_index(args.fund_code, start, end, args.method, topline=args.topline)
    else:
        rs = run_backtest(args.fund_code, start, end, args.method, topline=args.topline)

    summary = summarize(rs, args.threshold)
    print(f"=== 基金 {args.fund_code} 方法 {args.method} 回测 {start}~{end} ===")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print("\n每日明细:")
    print(f"  {'date':<12} {'est_pct':>10} {'act_pct':>10} {'abs_err':>10}")
    for r in rs:
        flag = "!" if r.abs_error_pp > args.threshold else " "
        print(f"  {r.trade_date.isoformat()}  {r.estimated_change_pct:+8.3f}%  {r.actual_change_pct:+8.3f}%  {r.abs_error_pp:>8.3f} {flag}")
    out_path = write_csv(rs, args.fund_code, args.method, start, end)
    print(f"\n落盘 → {out_path}")
