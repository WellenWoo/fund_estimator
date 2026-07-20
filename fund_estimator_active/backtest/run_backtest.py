"""backtest/run_backtest.py — 主动基金回测引擎

对历史每个交易日:
  1. 找到 T-1 NAV 与今日 NAV
  2. 找 T-1 季报持仓 (如果季报还没披露, 用上一季)
  3. 用 6 种算法分别估算
  4. 对比官方 NAV, 记 |error|
  5. 聚合 MAE / RMSE / MAX / over_th
"""
from __future__ import annotations
import sys
import csv
import math
from datetime import date as Date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from data_sources.eastmoney.nav_history import fetch_history
from data_sources.eastmoney.holdings_full import fetch_full_holdings
from data_sources.eastmoney.holding import fetch_top10, fetch_fund_meta
from data_sources.benchmark.get_benchmark import benchmark_return, list_benchmarks
from data_sources.sina.history import fetch_kline, get_return_pct
from core.models import FundHolding, StockPosition
from core import config
from estimators.holdings_based import estimate_v_active_top10
from estimators.benchmark_proxy import estimate_v_active_bench
from estimators.alpha_residual import estimate_v_active_alpha
from estimators.blend import estimate_v_active_top10_blend, estimate_v_active_top10_resid


def get_stock_returns(codes: list[str], t1_date: Date, today: Date,
                      fallback_pct: float = 0.0) -> dict[str, float]:
    """取每只股票在 [t1_date, today] 区间的涨跌幅 (decimal)。"""
    out: dict[str, float] = {}
    for code in codes:
        r = get_return_pct(code, t1_date, today)
        out[code] = r if r is not None else fallback_pct
    return out


def _to_fund_holding_from_top10(top10: list[StockPosition], fund_code: str,
                                fund_name: str, stock_pos_pct: float = 95.0) -> FundHolding:
    """把轻量 top10 + 总仓位 包成 FundHolding (weight_pct 留 0, 残差算法用 stock_pos 兜底)。"""
    return FundHolding(
        fund_code=fund_code, fund_name=fund_name,
        report_date=Date.today(),
        positions=top10,
        stock_position_pct=stock_pos_pct,
        cash_position_pct=100.0 - stock_pos_pct,
    )


def _load_quotes_from_klines(codes: list[str], t1_date: Date, today: Date) -> dict[str, float]:
    """从缓存的 kline 拉日收盘价, 计算 [t1, today] 区间的涨跌幅。"""
    quotes: dict[str, float] = {}
    for code in codes:
        rows = fetch_kline(code, scale_days=300)
        c1 = c2 = None
        for r in rows:
            d = r.get("date")
            if d == t1_date:
                c1 = r.get("close")
            if d == today:
                c2 = r.get("close")
        if c1 and c2 and c1 > 0:
            quotes[code] = (c2 - c1) / c1
        else:
            quotes[code] = 0.0
    return quotes


def run_one_day(today: Date, nav_history: list[dict],
                holding: FundHolding, alpha: float = 0.5,
                primary_bench: str = "csi1000") -> dict:
    """跑一天的所有算法, 返回结果 dict。"""
    # 找 T-1
    today_d = today
    sorted_nav = sorted([r for r in nav_history if r.get("date")], key=lambda r: r["date"])
    t1_row = None
    for r in sorted_nav:
        if r["date"] < today_d:
            t1_row = r
    if not t1_row:
        return {}
    t1_date = t1_row["date"]
    t1_nav = t1_row["nav"]
    # 今日官方 NAV
    off_row = next((r for r in sorted_nav if r["date"] == today_d), None)
    if not off_row:
        return {}
    off_nav = off_row["nav"]
    off_pct = (off_nav - t1_nav) / t1_nav

    # top10 股票的真实涨跌
    top10 = holding.top10()
    codes = [p.code for p in top10]
    quotes = _load_quotes_from_klines(codes, t1_date, today_d)

    # 各 benchmark 涨跌
    bench_returns = {}
    for key, _ in list_benchmarks():
        r = benchmark_return(key, t1_date, today_d)
        bench_returns[key] = r if r is not None else 0.0

    # 跑算法
    results: dict = {"date": today_d.isoformat(), "t1_date": t1_date.isoformat(),
                      "t1_nav": t1_nav, "official_nav": off_nav, "official_pct": off_pct}

    # 1. v_active_top10
    e = estimate_v_active_top10(holding, t1_nav, today_d, quotes)
    if e:
        results["v_active_top10"] = (e.estimated_nav, e.error_pp() if e.official_nav else None)
        results["v_active_top10_est_pct"] = e.estimated_change_pct

    # 2-5. v_active_bench_{key}
    for key in ("csi300", "csi500", "csi1000", "cyb"):
        e = estimate_v_active_bench(t1_nav, today_d, t1_date,
                                    bench_returns.get(key, 0.0), key)
        # 注入 official
        e.official_nav = off_nav
        e.official_change_pct = off_pct
        results[f"v_active_bench_{key}"] = (e.estimated_nav, e.error_pp())
        results[f"v_active_bench_{key}_est_pct"] = e.estimated_change_pct

    # 6. v_active_top10_blend (主推)
    e = estimate_v_active_top10_blend(holding, t1_nav, today_d, t1_date,
                                      quotes, bench_returns.get(primary_bench, 0.0),
                                      primary_bench, alpha=alpha)
    e.official_nav = off_nav
    e.official_change_pct = off_pct
    results[f"v_active_top10_blend_{primary_bench}_a{alpha}"] = (e.estimated_nav, e.error_pp())
    results["v_active_top10_blend_est_pct"] = e.estimated_change_pct

    # 7. v_active_alpha
    e = estimate_v_active_alpha(holding, t1_nav, today_d, t1_date,
                                quotes, bench_returns.get(primary_bench, 0.0),
                                primary_bench, alpha_drift=0.0)
    if e:
        e.official_nav = off_nav
        e.official_change_pct = off_pct
        results["v_active_alpha"] = (e.estimated_nav, e.error_pp())

    # 8. v_active_top10_resid_{key}
    for key in ("csi1000", "cyb", "csi500"):
        e = estimate_v_active_top10_resid(holding, t1_nav, today_d, t1_date,
                                          quotes, bench_returns.get(key, 0.0), key)
        if e:
            e.official_nav = off_nav
            e.official_change_pct = off_pct
            results[f"v_active_top10_resid_{key}"] = (e.estimated_nav, e.error_pp())

    return results


def aggregate(results: list[dict], methods: list[str]) -> dict:
    """聚合 MAE / RMSE / MAX / over_th。"""
    summary = {}
    for m in methods:
        errs = []
        for r in results:
            v = r.get(m)
            if isinstance(v, tuple) and v[1] is not None:
                errs.append(abs(v[1]))
        if not errs:
            continue
        mae = sum(errs) / len(errs)
        rmse = math.sqrt(sum(e * e for e in errs) / len(errs))
        mx = max(errs)
        over = sum(1 for e in errs if e > 0.5)
        summary[m] = {
            "N": len(errs),
            "MAE": round(mae, 4),
            "RMSE": round(rmse, 4),
            "MAX": round(mx, 4),
            "over_th": f"{over}/{len(errs)}",
        }
    return summary


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2026-04-25")
    ap.add_argument("--end", default="2026-07-15")
    ap.add_argument("--alpha", type=float, default=0.5)
    ap.add_argument("--bench", default="csi1000")
    args = ap.parse_args()

    start = Date.fromisoformat(args.start)
    end = Date.fromisoformat(args.end)

    print(f"== 主动基金 160211 回测 ({args.start} ~ {args.end}) ==")
    print(f"参数: alpha={args.alpha}, primary_bench={args.bench}")

    # 拉 NAV
    nav_history = fetch_history("160211", start=Date(2026, 1, 1), end=end, force=False)
    if not nav_history:
        print("ERR: 拉不到 NAV")
        return
    print(f"拉取 NAV: {len(nav_history)} 行")

    # 拉持仓 (轻量)
    top10 = fetch_top10("160211")
    print(f"top10 持仓: {len(top10)} 只")
    meta = fetch_fund_meta("160211")
    stock_pos = meta.get("stock_position_pct", 95.0)
    fund_name = meta.get("name", config.FUND_NAME)
    print(f"基金: {fund_name}, 股票仓位: {stock_pos}%")
    holding = _to_fund_holding_from_top10(top10, "160211", fund_name, stock_pos)

    # 找交易日
    trading_days = sorted([r["date"] for r in nav_history if start <= r["date"] <= end])
    print(f"交易日: {len(trading_days)} 天")

    # 跑回测
    all_results = []
    for td in trading_days:
        r = run_one_day(td, nav_history, holding,
                        alpha=args.alpha, primary_bench=args.bench)
        if r:
            all_results.append(r)

    # 聚合
    methods = [k for k in all_results[0].keys()
               if k not in ("date", "t1_date", "t1_nav", "official_nav", "official_pct")
               and not k.endswith("_est_pct")]
    summary = aggregate(all_results, methods)

    # 排序输出
    print("\n=== 多算法对比 ===")
    print(f"{'方法':<40} {'N':>4} {'MAE':>8} {'RMSE':>8} {'MAX':>8} {'over':>10}")
    print("-" * 90)
    for m, s in sorted(summary.items(), key=lambda x: x[1]["MAE"]):
        print(f"{m:<40} {s['N']:>4} {s['MAE']:>7.4f}pp {s['RMSE']:>7.4f}pp "
              f"{s['MAX']:>7.4f}pp {s['over_th']:>10}")

    if summary:
        best = min(summary.items(), key=lambda x: x[1]["MAE"])
        print(f"\n>> 最佳: {best[0]} (MAE={best[1]['MAE']}pp)")

    # 落盘
    out_path = config.RESULTS_DIR / f"backtest_160211_{args.start}_{args.end}.csv"
    with out_path.open("w", newline="", encoding="utf-8") as f:
        if all_results:
            w = csv.DictWriter(f, fieldnames=list(all_results[0].keys()))
            w.writeheader()
            for r in all_results:
                w.writerow(r)
    print(f"\n落盘: {out_path}")


if __name__ == "__main__":
    main()
