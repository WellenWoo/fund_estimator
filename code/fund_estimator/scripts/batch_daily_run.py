"""批量回放（多天）—— scripts/batch_daily_run.py。

README §3.2 的入口。对一个日期区间逐日估值 + 汇总，并把每日误差与聚合结果
落盘到 .cache/，供 dashboard 使用。

修复 ITERATIONS.md Iteration 3 记录的 bug：
- 先预取全区间 NAV → 构建 trading_days 集合；
- 非交易日提前跳过（estimate_for_day 内部已判断 NAV 缺失返回 None）；
- 预取用完整缓存，不用 force=True 覆盖。

用法::

    python code/fund_estimator/scripts/batch_daily_run.py \
        --start 2026-04-25 --end 2026-07-13 --method v_index_full_no_cash
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
from fund_estimator.core.models import THRESHOLD_PP  # noqa: E402
from fund_estimator.estimators.holdings_based import DEFAULT_METHOD, METHODS, METHOD_LABELS  # noqa: E402


def run(
    method: str,
    start: str,
    end: str,
    fund_code: str = FUND_CODE,
    force: bool = False,
) -> dict:
    need_stocks = method in ("v_top10", "v_index_blend", "v_residual_uncovered")
    inputs = load_common_inputs(
        fund_code, start, end,
        with_holdings=True, with_stocks=need_stocks, force=force,
    )
    result = backtest_range(inputs, method, start, end)
    stats = result.stats()
    stats["label"] = METHOD_LABELS.get(method, method)

    # 落盘每日误差
    cdir = cache_dir()
    daily_path = os.path.join(cdir, f"batch_{method}_{start}_{end}.csv")
    with open(daily_path, "w", encoding="utf-8", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["date", "t1_date", "t1_nav", "estimated_nav", "official_nav",
                    "estimated_change_pct", "official_change_pct", "error_pp", "over_threshold"])
        for c in result.valid:
            w.writerow([
                c.estimate.today, c.estimate.t1_date, c.estimate.t1_nav,
                c.estimate.estimated_nav, c.official_nav,
                c.estimate.estimated_change_pct,
                round(c.official_change_pct, 4) if c.official_change_pct is not None else "",
                round(c.error_pp, 4), int(bool(c.over_threshold)),
            ])
    stats["daily_csv"] = daily_path
    stats["skipped_non_trading"] = "（非交易日已自动跳过）"
    return stats


def main(argv: Optional[list[str]] = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
    parser = argparse.ArgumentParser(description="批量回放（多天）")
    parser.add_argument("--method", default=DEFAULT_METHOD, choices=METHODS)
    parser.add_argument("--start", default="2026-04-25")
    parser.add_argument("--end", default="2026-07-14")
    parser.add_argument("--fund", default=FUND_CODE)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args(argv)

    stats = run(args.method, args.start, args.end, args.fund, force=args.force)
    print(json.dumps(stats, ensure_ascii=False, indent=2))
    if stats.get("n", 0):
        print(f"\n阈值 {THRESHOLD_PP}pp：超阈值 {stats['over_ratio']}，"
              f"MAE={stats['mae_pp']}pp，MAX={stats['max_pp']}pp")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
