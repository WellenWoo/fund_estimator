"""迭代追踪器：对一个基金的同一个回测窗口，跑多个估算器，横向对比，
选出 MAE 最小的方法作为当前"主推"。

输出:
- .cache/iterations_{fund}.json — 历次迭代的 (方法, MAE, 阈值, 时间)
- stdout 摘要
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from fund_estimator.backtest.run_backtest import (  # noqa: E402
    run_backtest,
    summarize,
)
from fund_estimator.backtest.run_index_backtest import (  # noqa: E402
    run_backtest_with_index,
)


METHOD_TABLE = {
    "v_top10": ("纯持仓还原 top10", "old"),
    "v_residual": ("top10 + 现金拖累", "old"),
    "v_residual_uncovered": ("top10 + uncovered 代理", "old"),
    "v_index_full": ("创业板指全代理 (含 cash_drag)", "new"),
    "v_index_full_no_cash": ("创业板指全代理 (无 cash_drag)", "new"),
    "v_index_blend": ("top10 + 创业板指混合", "new"),
}


def iterate(
    fund_code: str,
    start: date,
    end: date,
    methods: list[str],
    threshold_pp: float = 0.5,
) -> dict:
    """跑一遍多种方法, 输出对比."""
    all_results = {}
    for m in methods:
        if "v_index" in m:
            rs = run_backtest_with_index(fund_code, start, end, m, topline=10)
        else:
            rs = run_backtest(fund_code, start, end, m, topline=10)
        s = summarize(rs, threshold_pp)
        all_results[m] = s
    return all_results


def pick_best(results: dict) -> tuple[str, dict]:
    best_m, best_s = None, {"MAE_pp": float("inf")}
    for m, s in results.items():
        if s.get("n", 0) == 0:
            continue
        if s["MAE_pp"] < best_s["MAE_pp"]:
            best_m, best_s = m, s
    return best_m, best_s


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--fund-code", default="160223")
    p.add_argument("--start", default="2026-04-25")
    p.add_argument("--end", default="2026-07-06")
    p.add_argument(
        "--methods",
        default="v_top10,v_index_full,v_index_full_no_cash,v_index_blend,v_residual_uncovered",
        help="comma-separated method names",
    )
    p.add_argument("--threshold", type=float, default=0.5)
    args = p.parse_args()

    start = date.fromisoformat(args.start)
    end = date.fromisoformat(args.end)
    methods = args.methods.split(",")

    results = iterate(args.fund_code, start, end, methods, args.threshold)

    print(f"=== 基金 {args.fund_code} 迭代对比 ({start}~{end}) ===")
    print()
    print(f"{'方法':<30} {'N':>4} {'MAE_pp':>8} {'RMSE':>8} {'MAX':>8} {'over_th':>10}")
    print("-" * 70)
    for m, s in results.items():
        label, _ = METHOD_TABLE.get(m, (m, "?"))
        if s.get("n", 0) == 0:
            print(f"{label:<30} {0:>4}  {'N/A':>8}")
            continue
        print(
            f"{label:<30} {s['n']:>4}  {s['MAE_pp']:>+8.4f}  {s['RMSE_pp']:>+8.4f}  "
            f"{s['MAX_pp']:>+8.4f}  {s[f'days_over_{args.threshold}pp']:>4}/{s['n']}"
        )
    best_m, best_s = pick_best(results)
    if best_m is not None:
        label, _ = METHOD_TABLE.get(best_m, (best_m, "?"))
        print(f"\n>> 最佳: {label} (MAE={best_s['MAE_pp']:.4f}pp)")
