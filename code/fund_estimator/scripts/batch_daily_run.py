"""批量跑多日的 daily_close_estimate, 生成完整的 daily_log.csv 并汇总误差。

用法:
    python -m fund_estimator.scripts.batch_daily_run --start 2026-04-25 --end 2026-07-06 --method v_index_full
"""

from __future__ import annotations

import argparse
import csv
import statistics
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from fund_estimator.data_sources.cache import CACHE_DIR  # noqa: E402
from fund_estimator.data_sources.eastmoney.nav_history import (  # noqa: E402
    fetch_history,
)
from fund_estimator.scripts.daily_close_estimate import (  # noqa: E402
    estimate_for_day,
    METHODS_REGISTRY,
)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--fund-code", default="160223")
    p.add_argument("--start", default="2026-04-25")
    p.add_argument("--end", default="2026-07-06")
    p.add_argument("--method", default="v_index_full", choices=list(METHODS_REGISTRY.keys()))
    p.add_argument("--threshold", type=float, default=0.5)
    args = p.parse_args()

    start = date.fromisoformat(args.start)
    end = date.fromisoformat(args.end)

    # 提前拉取一次全部历史 NAV, 减少后续反复拉取
    full_rows = fetch_history(args.fund_code, start=start - timedelta(days=20), end=end)
    trading_days = {r["date"] for r in full_rows if r["date"] and r["nav"] is not None}

    cur = start
    rows: list[dict] = []
    skipped_non_trading = 0
    while cur <= end:
        # 先检查是否交易日
        if cur not in trading_days:
            skipped_non_trading += 1
            cur += timedelta(days=1)
            continue
        try:
            r = estimate_for_day(args.fund_code, cur, args.method)
            if r["official_nav"] is None:
                # 今天 NAV 尚未公布 (未来交易日)
                skipped_non_trading += 1
                cur += timedelta(days=1)
                continue
            r["trade_date"] = r.pop("today")
            r["abs_error_pp"] = round(
                abs(r["estimated_nav"] - r["official_nav"]), 4
            )
            actual_chg = (r["official_nav"] - r["t1_nav"]) / r["t1_nav"] * 100.0
            est_chg = r["estimated_change_pct"]
            r["abs_error_ppct"] = round(abs(est_chg - actual_chg), 4)
            r["rel_error_ppct"] = round(est_chg - actual_chg, 4)
            rows.append(r)
            print(
                f"  {r['trade_date']}  est={r['estimated_nav']:.4f}  off={r['official_nav']:.4f}  "
                f"|err|={r['abs_error_ppct']:.4f}pp  {'!' if r['abs_error_ppct'] > args.threshold else ' '}",
                flush=True,
            )
        except SystemExit:
            skipped_non_trading += 1
            cur += timedelta(days=1)
            continue
        except Exception as e:
            print(f"  {cur}: FAIL {e}", flush=True)
        cur += timedelta(days=1)

    # 写 daily_log
    log_path = CACHE_DIR / f"daily_batch_{args.fund_code}_{args.method}_{start.isoformat()}_{end.isoformat()}.csv"
    if rows:
        keys = list(rows[0].keys())
        with log_path.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(f, fieldnames=keys)
            w.writeheader()
            for r in rows:
                w.writerow(r)
        print(f"\n落盘 → {log_path}")

    # 汇总
    if not rows:
        print("\n无有效数据")
        return
    abs_errs = [r["abs_error_ppct"] for r in rows]
    rel_errs = [r["rel_error_ppct"] for r in rows]
    days_over = sum(1 for e in abs_errs if e > args.threshold)

    print("\n=== 汇总 ===")
    print(f"  N          = {len(rows)}")
    print(f"  非交易日跳过 = {skipped_non_trading}")
    print(f"  MAE (pp)   = {statistics.mean(abs_errs):.4f}")
    print(f"  RMSE (pp)  = {statistics.sqrt(statistics.fmean(e * e for e in rel_errs)):.4f}")
    print(f"  Mean err   = {statistics.mean(rel_errs):+.4f} pp (bias)")
    print(f"  Median     = {statistics.median(abs_errs):.4f}")
    print(f"  Max        = {max(abs_errs):.4f}")
    print(f"  days over  = {days_over}/{len(rows)} (>{args.threshold}pp)")


if __name__ == "__main__":
    main()
