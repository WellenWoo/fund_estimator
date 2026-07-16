"""每日盘后生产脚本：对 LOF 160223 在当日 15:00 后做一次估值，
并在官方净值公布后自动拉取对比，记录误差。

执行模式:
- 盘后模式（默认）：在 15:00-21:00 之间运行 → 计算并打印估算值，等待人工校对。
- 对比模式：--fetch-official → 拉官方 NAV，输出对比，并落盘到 .cache/daily_log.csv。

用法:
    1. 当天 15:05:  python -m fund_estimator.scripts.daily_close_estimate
    2. 当天 21:00:  python -m fund_estimator.scripts.daily_close_estimate --fetch-official
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import urllib.request
import urllib.parse
import re
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from fund_estimator.backtest.run_backtest import (  # noqa: E402
    estimator_v_top10,
    estimator_v_residual,
)
from fund_estimator.backtest.run_index_backtest import (  # noqa: E402
    estimator_v_index_chinext_full,
    estimator_v_index_chinext_full_no_cash,
)
from fund_estimator.data_sources.cache import CACHE_DIR  # noqa: E402
from fund_estimator.data_sources.eastmoney.holdings_full import (  # noqa: E402
    fetch_holdings,
)
from fund_estimator.data_sources.eastmoney.nav_history import (  # noqa: E402
    fetch_history,
)
from fund_estimator.data_sources.sina.history import fetch_kline  # noqa: E402
from fund_estimator.backtest.run_backtest import pick_quarter  # noqa: E402


METHODS_REGISTRY = {
    "v_top10": estimator_v_top10,
    "v_residual": estimator_v_residual,
    "v_index_full": estimator_v_index_chinext_full,
    "v_index_full_no_cash": estimator_v_index_chinext_full_no_cash,
}


def get_yesterday_today():
    """根据当前时间决定 today 与 T-1，用于盘后对比。
    A 股开盘: 9:30-11:30, 13:00-15:00。
    盘后 15:00-21:00: today = 今日, T-1 = 上一交易日。
    盘前 / 盘中: 退化成"上一交易日" vs "再上一交易日" 对比。
    """
    now = datetime.now()
    today = now.date()
    return today, today - timedelta(days=1)


def fetch_official_nav(fund_code: str, target_date: date) -> float | None:
    """从天天基金 JSONP 拿最新官方估算 + 已公布的真实 NAV。
    注意: jzrq 是 'NAV 对应的交易日', 不是 '发布时间'。"""
    url = f"https://fundgz.1234567.com.cn/js/{fund_code}.js?rt={int(datetime.now().timestamp())}"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=10) as r:
            raw = r.read().decode("utf-8", errors="ignore")
        m = re.search(r'"dwjz":"([\d.]+)"', raw)
        if m:
            return float(m.group(1))
    except Exception:
        pass
    return None


def close_on_in_window(symbol: str, d: date) -> float | None:
    """拿某交易日的收盘价（带缓存）。窗口不够就扩。"""
    for w in (60, 120, 252):
        try:
            rows = fetch_kline(symbol, w)
            for r in rows:
                if r["date"] == d.isoformat():
                    return float(r["close"])
        except Exception:
            continue
    return None


def estimate_for_day(fund_code: str, today: date, method: str = "v_index_full") -> dict:
    """对单一交易日做估算, 返回 dict 含详细数据."""
    if method not in METHODS_REGISTRY:
        raise ValueError(f"unknown method: {method}")
    estimator = METHODS_REGISTRY[method]

    # 1) T-1 NAV（不强制 force，以免覆盖预取的完整缓存）
    fetch_start = today - timedelta(days=20)
    fetch_end = today
    rows = fetch_history(fund_code, start=fetch_start, end=fetch_end, force=False)
    # rows 至少需要 [T-1, today] 两行
    rows_sorted = sorted(rows, key=lambda r: r["date"])
    prev = None
    cur = None
    for r in rows_sorted:
        if r["date"] < today and r["nav"] is not None:
            prev = r
        if r["date"] == today and r["nav"] is not None:
            cur = r
    if prev is None:
        raise SystemExit(f"no T-1 NAV available before {today}")
    t1_nav = prev["nav"]
    t1_date = prev["date"]

    # 2) 持仓
    y, m = pick_quarter(today)
    _, holdings = fetch_holdings(fund_code, y, m, topline=10)

    # 3) 收盘价
    if method in ("v_index_full", "v_index_full_no_cash"):
        prev_close = {"INDEX": close_on_in_window("sz399006", t1_date)}
        today_close = {"INDEX": close_on_in_window("sz399006", today)}
    else:
        prev_close = {}
        today_close = {}
        for h in holdings:
            code = h["code"]
            sym = f"sz{code}" if code.startswith("3") else f"sh{code}"
            p1 = close_on_in_window(sym, t1_date)
            p2 = close_on_in_window(sym, today)
            if p1 and p2:
                prev_close[code] = p1
                today_close[code] = p2

    # 4) 估算
    est_nav = estimator(holdings, prev_close, today_close, t1_nav)
    est_change_pct = (est_nav - t1_nav) / t1_nav * 100.0

    return {
        "fund_code": fund_code,
        "today": today.isoformat(),
        "t1_date": t1_date.isoformat(),
        "t1_nav": t1_nav,
        "estimated_nav": est_nav,
        "estimated_change_pct": round(est_change_pct, 4),
        "method": method,
        "official_nav": cur["nav"] if cur else None,
        "official_change_pct": cur["change_pct"] if cur else None,
    }


def append_daily_log(record: dict, log_path: Path):
    """追加一行到 .cache/daily_log.csv (header 自动)."""
    new_file = not log_path.exists()
    with log_path.open("a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if new_file:
            writer.writerow(
                [
                    "log_time",
                    "fund_code",
                    "trade_date",
                    "t1_date",
                    "t1_nav",
                    "method",
                    "estimated_nav",
                    "estimated_change_pct",
                    "official_nav",
                    "official_change_pct",
                    "abs_error_pp",
                    "rel_error_pp",
                ]
            )
        log_time = datetime.now().isoformat()
        # compute errors
        abs_err = ""
        rel_err = ""
        if record["official_nav"] is not None and record["estimated_nav"] is not None and record["t1_nav"]:
            actual_change = (record["official_nav"] - record["t1_nav"]) / record["t1_nav"] * 100.0
            abs_err = round(abs(record["estimated_change_pct"] - actual_change), 4)
            rel_err = round(record["estimated_change_pct"] - actual_change, 4)
        writer.writerow(
            [
                log_time,
                record["fund_code"],
                record["today"],
                record["t1_date"],
                record["t1_nav"],
                record["method"],
                record["estimated_nav"],
                record["estimated_change_pct"],
                record["official_nav"] if record["official_nav"] is not None else "",
                record["official_change_pct"] if record["official_change_pct"] is not None else "",
                abs_err,
                rel_err,
            ]
        )


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--fund-code", default="160223")
    p.add_argument("--method", default="v_index_full_no_cash", choices=list(METHODS_REGISTRY.keys()))
    p.add_argument("--trade-date", help="ISO date, 默认 = 今日")
    p.add_argument("--fetch-official", action="store_true", help="拉官方 NAV 后才输出对比")
    args = p.parse_args()

    trade_date = date.fromisoformat(args.trade_date) if args.trade_date else date.today()

    rec = estimate_for_day(args.fund_code, trade_date, args.method)

    # 加一个交叉检验：拿 ttfund 实时 JSONP, 仅当 jzrq==trade_date 时才信。
    # 否则保留历史 NAV 作为权威值。
    if args.fetch_official:
        live_url = f"https://fundgz.1234567.com.cn/js/{args.fund_code}.js?rt={int(datetime.now().timestamp())}"
        try:
            req = urllib.request.Request(live_url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=10) as r:
                raw = r.read().decode("utf-8", errors="ignore")
            m_date = re.search(r'"jzrq":"([^"]+)"', raw)
            m_nav = re.search(r'"dwjz":"([\d.]+)"', raw)
            if m_date and m_nav and m_date.group(1) == trade_date.isoformat():
                rec["official_nav"] = float(m_nav.group(1))
        except Exception as e:
            print(f"[warn] live fetch: {e}", file=sys.stderr)

    print(f"=== {args.fund_code} 盘后估值 ({args.method}) ===")
    print(json.dumps(rec, ensure_ascii=False, indent=2))
    if rec["official_nav"] is not None:
        diff = rec["estimated_nav"] - rec["official_nav"]
        rel = diff / rec["official_nav"] * 100.0
        print(f"\n对比官方 NAV {rec['official_nav']}:  差异 {diff:+.4f} ({rel:+.4f}%)")
    log_path = CACHE_DIR / "daily_log.csv"
    append_daily_log(rec, log_path)
    print(f"\n落盘 → {log_path}")
