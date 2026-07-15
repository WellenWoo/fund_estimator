"""多方法横向对比 + 选优 + 落盘。

README §3.3 / ITERATIONS.md「Iteration 结果对比」的实现：
- 对全部 5 种算法在同一区间跑回测；
- 输出对比表（MAE / RMSE / MEAN / MAX / over_threshold）；
- 选出 MAE 最小且 over_threshold 最少的「最佳算法」；
- 把结果写入 .cache/iteration_results.csv 与 .cache/daily_errors.csv，
  供 gen_dashboard.py 读取生成 HTML。
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from typing import Optional

_THIS = os.path.dirname(os.path.abspath(__file__))
_CODE_ROOT = os.path.dirname(os.path.dirname(_THIS))
if _CODE_ROOT not in sys.path:
    sys.path.insert(0, _CODE_ROOT)

from fund_estimator.backtest.run_backtest import (  # noqa: E402
    load_common_inputs,
    backtest_range,
    FUND_CODE,
)
from fund_estimator.data_sources.cache import cache_dir  # noqa: E402
from fund_estimator.estimators.holdings_based import (  # noqa: E402
    METHODS,
    METHOD_LABELS,
    DEFAULT_METHOD,
)


ITER_RESULTS_CSV = "iteration_results.csv"
DAILY_ERRORS_CSV = "daily_errors.csv"


def run_all(
    fund_code: str = FUND_CODE,
    start: str = "2026-04-25",
    end: str = "2026-07-14",
    *,
    methods: Optional[list[str]] = None,
    force: bool = False,
) -> tuple[list[dict], list[dict]]:
    """对全部方法回测。返回 (stats_rows, daily_rows)。"""
    methods = methods or METHODS
    # 有任何持仓还原类算法就抓成分股日线
    need_stocks = any(m in ("v_top10", "v_index_blend", "v_residual_uncovered") for m in methods)
    inputs = load_common_inputs(
        fund_code, start, end,
        with_holdings=True, with_stocks=need_stocks, force=force,
    )

    stats_rows: list[dict] = []
    daily_rows: list[dict] = []
    for m in methods:
        result = backtest_range(inputs, m, start, end)
        s = result.stats()
        s["label"] = METHOD_LABELS.get(m, m)
        stats_rows.append(s)
        for c in result.valid:
            daily_rows.append(
                {
                    "method": m,
                    "date": c.estimate.today,
                    "t1_nav": c.estimate.t1_nav,
                    "estimated_nav": c.estimate.estimated_nav,
                    "official_nav": c.official_nav,
                    "estimated_change_pct": c.estimate.estimated_change_pct,
                    "official_change_pct": round(c.official_change_pct, 4) if c.official_change_pct is not None else "",
                    "error_pp": round(c.error_pp, 4),
                    "over_threshold": int(bool(c.over_threshold)),
                }
            )
    return stats_rows, daily_rows


def pick_best(stats_rows: list[dict]) -> Optional[dict]:
    """选优：over_threshold 最少 → MAE 最小。"""
    valid = [s for s in stats_rows if s.get("n", 0) > 0]
    if not valid:
        return None
    return sorted(valid, key=lambda s: (s["over_threshold"], s["mae_pp"]))[0]


def _write_csv(path: str, rows: list[dict], fieldnames: list[str]) -> None:
    with open(path, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=fieldnames)
        w.writeheader()
        for r in rows:
            w.writerow({k: r.get(k, "") for k in fieldnames})


def save_results(stats_rows: list[dict], daily_rows: list[dict]) -> tuple[str, str]:
    """把对比结果落盘到 .cache/，供 dashboard 读取。返回两个 CSV 路径。"""
    cdir = cache_dir()
    stats_path = os.path.join(cdir, ITER_RESULTS_CSV)
    daily_path = os.path.join(cdir, DAILY_ERRORS_CSV)
    _write_csv(
        stats_path,
        stats_rows,
        ["method", "label", "start", "end", "n", "mae_pp", "rmse_pp", "mean_pp", "max_pp", "over_threshold", "over_ratio"],
    )
    _write_csv(
        daily_path,
        daily_rows,
        ["method", "date", "t1_nav", "estimated_nav", "official_nav",
         "estimated_change_pct", "official_change_pct", "error_pp", "over_threshold"],
    )
    return stats_path, daily_path


def print_table(stats_rows: list[dict], best: Optional[dict]) -> None:
    print("\n===== 5 种算法横向对比 =====")
    header = f"{'算法':<26}{'N':>4}{'MAE':>9}{'RMSE':>9}{'MEAN':>9}{'MAX':>9}{'超阈值':>9}"
    print(header)
    print("-" * len(header))
    for s in sorted(stats_rows, key=lambda x: x.get("mae_pp", 1e9)):
        if s.get("n", 0) == 0:
            print(f"{s['method']:<26}{'0':>4}  (无有效样本)")
            continue
        star = " ⭐" if best and s["method"] == best["method"] else ""
        print(
            f"{s['method']:<26}{s['n']:>4}{s['mae_pp']:>9.4f}{s['rmse_pp']:>9.4f}"
            f"{s['mean_pp']:>9.4f}{s['max_pp']:>9.4f}{s['over_ratio']:>9}{star}"
        )
    if best:
        print(f"\n🏆 最佳算法: {best['method']} ({best.get('label','')}) "
              f"MAE={best['mae_pp']}pp, 超阈值={best['over_ratio']}")


def main(argv: Optional[list[str]] = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
    parser = argparse.ArgumentParser(description="多方法横向对比 + 选优")
    parser.add_argument("--fund", default=FUND_CODE)
    parser.add_argument("--start", default="2026-04-25")
    parser.add_argument("--end", default="2026-07-14")
    parser.add_argument("--methods", default="", help="逗号分隔，默认全部 5 种")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--json", action="store_true", help="额外打印 JSON")
    args = parser.parse_args(argv)

    methods = [m.strip() for m in args.methods.split(",") if m.strip()] or None
    stats_rows, daily_rows = run_all(args.fund, args.start, args.end, methods=methods, force=args.force)
    best = pick_best(stats_rows)
    print_table(stats_rows, best)
    stats_path, daily_path = save_results(stats_rows, daily_rows)
    print(f"\n结果已写入:\n  {stats_path}\n  {daily_path}")
    if args.json:
        print(json.dumps({"stats": stats_rows, "best": best}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
