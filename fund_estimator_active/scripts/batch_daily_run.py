"""scripts/batch_daily_run.py — 批量回放多天

跑一段日期区间, 每天调单日脚本的核心逻辑, 输出每日 + 聚合结果。
"""
from __future__ import annotations
import sys
import csv
import math
import argparse
from datetime import date as Date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from data_sources.eastmoney.nav_history import fetch_history
from data_sources.eastmoney.holdings_full import fetch_full_holdings
from data_sources.eastmoney.holding import fetch_top10, fetch_fund_meta
from data_sources.benchmark.get_benchmark import benchmark_return
from core import config
from core.models import StockPosition
from backtest.run_backtest import _to_fund_holding_from_top10, _load_quotes_from_klines
from estimators.holdings_based import estimate_v_active_top10
from estimators.benchmark_proxy import estimate_v_active_bench
from estimators.alpha_residual import estimate_v_active_alpha
from estimators.blend import estimate_v_active_top10_blend, estimate_v_active_top10_resid


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2026-04-25")
    ap.add_argument("--end", default="2026-07-15")
    ap.add_argument("--method", default="v_active_top10_blend")
    ap.add_argument("--alpha", type=float, default=None,
                    help="长尾代理强度, 不指定则使用自适应 alpha")
    ap.add_argument("--bench", default="csi1000")
    args = ap.parse_args()

    fund_code = config.FUND_CODE
    start = Date.fromisoformat(args.start)
    end = Date.fromisoformat(args.end)

    print(f"== 主动基金 {fund_code} 批量回放 ({args.start} ~ {args.end}) ==")

    nav_history = fetch_history(fund_code, start=Date(2026, 1, 1), end=end, force=False)
    if not nav_history:
        print("ERR: 拉不到 NAV")
        return

    # 持仓 (优先完整持仓)
    holding = fetch_full_holdings(fund_code)
    meta = fetch_fund_meta(fund_code)
    fund_name = meta.get("name", config.FUND_NAME)
    stock_pos = meta.get("stock_position_pct", 95.0)

    if holding:
        holding.fund_name = fund_name
        holding.stock_position_pct = stock_pos
        holding.cash_position_pct = 100.0 - stock_pos
    else:
        top10 = fetch_top10(fund_code)
        holding = _to_fund_holding_from_top10(top10, fund_code, fund_name, stock_pos)

    top10 = holding.top10()
    codes = [p.code for p in top10]
    print(f"  基金: {fund_name}, top10: {len(top10)} 只, 股票仓位: {stock_pos}%")

    sorted_nav = sorted([r for r in nav_history if r.get("date")], key=lambda r: r["date"])
    trading_days = [r["date"] for r in sorted_nav if start <= r["date"] <= end]

    results: list[dict] = []
    skipped = 0
    for td in trading_days:
        t1_row = max((r for r in sorted_nav if r["date"] < td), key=lambda x: x["date"], default=None)
        if not t1_row:
            skipped += 1
            continue
        t1_date, t1_nav = t1_row["date"], t1_row["nav"]
        off_row = next((r for r in sorted_nav if r["date"] == td), None)
        if not off_row:
            skipped += 1
            continue
        off_nav = off_row["nav"]
        off_pct = (off_nav - t1_nav) / t1_nav

        quotes = _load_quotes_from_klines(codes, t1_date, td)
        bench_ret = benchmark_return(args.bench, t1_date, td) or 0.0

        # 自适应 alpha
        if args.alpha is None and holding:
            alpha_val = holding.adaptive_alpha(td)
        else:
            alpha_val = args.alpha or 0.5

        if args.method == "v_active_top10":
            est = estimate_v_active_top10(holding, t1_nav, td, t1_date, quotes)
        elif args.method.startswith("v_active_bench_"):
            key = args.method.replace("v_active_bench_", "")
            est = estimate_v_active_bench(t1_nav, td, t1_date, bench_ret, key,
                                           fund_code=fund_code, fund_name=fund_name)
        elif args.method == "v_active_top10_blend":
            est = estimate_v_active_top10_blend(holding, t1_nav, td, t1_date,
                                                quotes, bench_ret, args.bench, alpha=alpha_val)
        elif args.method == "v_active_alpha":
            est = estimate_v_active_alpha(holding, t1_nav, td, t1_date,
                                          quotes, bench_ret, args.bench)
        elif args.method.startswith("v_active_top10_resid_"):
            key = args.method.replace("v_active_top10_resid_", "")
            est = estimate_v_active_top10_resid(holding, t1_nav, td, t1_date,
                                                quotes, bench_ret, key)
        else:
            print(f"  ERR: 未知方法 {args.method}")
            return

        if not est:
            skipped += 1
            continue
        est.official_nav = off_nav
        est.official_change_pct = off_pct
        err = est.error_pp()
        results.append({
            "date": td.isoformat(),
            "t1_date": t1_date.isoformat(),
            "t1_nav": t1_nav,
            "est_nav": est.estimated_nav,
            "off_nav": off_nav,
            "est_pct": est.estimated_change_pct,
            "off_pct": off_pct,
            "err_pp": err,
            "method": est.method,
            "alpha": alpha_val,
        })
        print(f"  {td}  est={est.estimated_nav:.4f}  off={off_nav:.4f}  "
              f"|err|={abs(err):.4f}pp" if err is not None else
              f"  {td}  est={est.estimated_nav:.4f}  off=N/A")

    errs = [abs(r["err_pp"]) for r in results if r["err_pp"] is not None]
    if not errs:
        print("无有效结果")
        return
    mae = sum(errs) / len(errs)
    rmse = math.sqrt(sum(e * e for e in errs) / len(errs))
    bias = sum((r["err_pp"] or 0) for r in results) / len(results)
    mx = max(errs)
    over = sum(1 for e in errs if e > 0.5)

    print(f"\n=== 汇总 ({args.method}) ===")
    print(f"  N          = {len(errs)}")
    print(f"  跳过       = {skipped}")
    print(f"  MAE (pp)   = {mae:.4f}")
    print(f"  RMSE (pp)  = {rmse:.4f}")
    print(f"  Mean err   = {bias:+.4f} pp (bias)")
    print(f"  Max        = {mx:.4f}")
    print(f"  days over  = {over}/{len(errs)} (>0.5pp)")

    out_path = config.RESULTS_DIR / f"daily_batch_160211_{args.method}_{args.start}_{args.end}.csv"
    with out_path.open("w", newline="", encoding="utf-8") as f:
        if results:
            w = csv.DictWriter(f, fieldnames=list(results[0].keys()))
            w.writeheader()
            for r in results:
                w.writerow(r)
    print(f"\n落盘: {out_path}")


if __name__ == "__main__":
    main()
