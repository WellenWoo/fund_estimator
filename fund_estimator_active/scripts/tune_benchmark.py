"""scripts/tune_benchmark.py — Benchmark & alpha 自动调优

对每个候选 benchmark (csi300 / csi500 / csi1000 / cyb) 和 alpha ∈ [0.2, 0.8] 跑遍,
选 MAE 最低的组合作为生产参数。
"""
from __future__ import annotations
import sys
import math
from datetime import date as Date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from data_sources.eastmoney.nav_history import fetch_history
from data_sources.eastmoney.holding import fetch_top10, fetch_fund_meta
from data_sources.benchmark.get_benchmark import benchmark_return, list_benchmarks
from core import config
from backtest.run_backtest import _to_fund_holding_from_top10, _load_quotes_from_klines
from estimators.benchmark_proxy import estimate_v_active_bench
from estimators.blend import estimate_v_active_top10_blend, estimate_v_active_top10_resid


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2026-04-25")
    ap.add_argument("--end", default="2026-07-15")
    args = ap.parse_args()

    start = Date.fromisoformat(args.start)
    end = Date.fromisoformat(args.end)
    fund_code = config.FUND_CODE

    print(f"== Benchmark 调优 ({fund_code}, {args.start} ~ {args.end}) ==")

    nav_history = fetch_history(fund_code, start=Date(2026, 1, 1), end=end, force=False)
    if not nav_history:
        print("ERR: 拉不到 NAV")
        return
    top10 = fetch_top10(fund_code)
    meta = fetch_fund_meta(fund_code)
    fund_name = meta.get("name", config.FUND_NAME)
    stock_pos = meta.get("stock_position_pct", 95.0)
    holding = _to_fund_holding_from_top10(top10, fund_code, fund_name, stock_pos)
    codes = [p.code for p in top10]

    sorted_nav = sorted([r for r in nav_history if r.get("date")], key=lambda r: r["date"])
    trading_days = [r["date"] for r in sorted_nav if start <= r["date"] <= end]

    # 预计算所有 benchmark 的每日 return
    bench_returns_per_day: dict[str, dict[Date, float]] = {}
    for key, _ in list_benchmarks():
        d = {}
        for td in trading_days:
            t1 = max((r["date"] for r in sorted_nav if r["date"] < td), default=None)
            if t1:
                d[td] = benchmark_return(key, t1, td) or 0.0
        bench_returns_per_day[key] = d

    # 预计算每只股票的每日 return
    stock_returns_per_day: dict[str, dict[Date, float]] = {}
    for c in codes:
        d = {}
        for td in trading_days:
            t1 = max((r["date"] for r in sorted_nav if r["date"] < td), default=None)
            if t1:
                quotes = _load_quotes_from_klines([c], t1, td)
                d[td] = quotes.get(c, 0.0)
        stock_returns_per_day[c] = d

    # 评估每种 (bench, alpha) 组合
    best = None
    rows = []
    for key, _ in list_benchmarks():
        for alpha in (0.0, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 1.0):
            errs = []
            for td in trading_days:
                t1_row = max((r for r in sorted_nav if r["date"] < td), key=lambda x: x["date"], default=None)
                if not t1_row:
                    continue
                t1_date, t1_nav = t1_row["date"], t1_row["nav"]
                off_row = next((r for r in sorted_nav if r["date"] == td), None)
                if not off_row:
                    continue
                off_nav = off_row["nav"]
                # top10 内部归一化
                total_w = sum(p.weight_pct for p in top10)
                if total_w > 0:
                    top10_avg = sum((p.weight_pct / total_w) * stock_returns_per_day.get(p.code, {}).get(td, 0.0)
                                    for p in top10)
                else:
                    top10_avg = sum(stock_returns_per_day.get(p.code, {}).get(td, 0.0)
                                    for p in top10) / max(len(top10), 1)
                bench_ret = bench_returns_per_day.get(key, {}).get(td, 0.0)
                est_pct = (1 - alpha) * top10_avg + alpha * bench_ret
                est_nav = t1_nav * (1 + est_pct)
                err = (est_nav - off_nav) / off_nav * 100
                errs.append(abs(err))
            if not errs:
                continue
            mae = sum(errs) / len(errs)
            rmse = math.sqrt(sum(e * e for e in errs) / len(errs))
            over = sum(1 for e in errs if e > 0.5)
            row = {"bench": key, "alpha": alpha, "N": len(errs), "MAE": mae, "RMSE": rmse, "over_th": f"{over}/{len(errs)}"}
            rows.append(row)
            if best is None or mae < best["MAE"]:
                best = row

    rows.sort(key=lambda r: r["MAE"])
    print(f"\n=== (bench × alpha) 网格搜索 ===")
    print(f"{'bench':<10} {'alpha':>6} {'N':>4} {'MAE':>8} {'RMSE':>8} {'over':>10}")
    print("-" * 56)
    for r in rows[:15]:
        print(f"{r['bench']:<10} {r['alpha']:>6.2f} {r['N']:>4} {r['MAE']:>7.4f}pp {r['RMSE']:>7.4f}pp {r['over_th']:>10}")

    if best:
        print(f"\n>> 最佳组合: bench={best['bench']}, alpha={best['alpha']} "
              f"(MAE={best['MAE']:.4f}pp)")
        # 写入配置建议
        cfg_path = config.RESULTS_DIR / "tuned_params.json"
        import json
        with cfg_path.open("w", encoding="utf-8") as f:
            json.dump(best, f, indent=2, ensure_ascii=False)
        print(f"建议写入: {cfg_path}")


if __name__ == "__main__":
    main()
