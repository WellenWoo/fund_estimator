"""批量回放（多天）—— scripts/batch_daily_run.py。

README §3.2 的入口。对一个日期区间逐日估值 + 汇总，并把每日误差与聚合结果
落盘到 .cache/，供 dashboard 使用。

自动检测逻辑：
- 如果 --index-symbol 未指定，则从 lof_info.db 查询该基金的 tracker_index_code，
  自动解析为对应指数 symbol。
- 如果数据库中无该基金，fallback 到 sz399006（兼容旧用法）。

用法::

    python code/fund_estimator/scripts/batch_daily_run.py \
        --start 2026-04-25 --end 2026-07-13 --method v_index_full_no_cash

    # 指定指数
    python code/fund_estimator/scripts/batch_daily_run.py \
        --fund 160615 --index-symbol sh000300 --start 2026-04-25 --end 2026-07-13
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


DEFAULT_INDEX_SYMBOL = "sz399006"  # CLI fallback


def _detect_index_symbol(fund_code: str) -> Optional[str]:
    """从 lof_info.db 查询基金的跟踪指数并解析为 symbol。

    Returns
    -------
    str or None
        标准化 index symbol（如 "sh000300"），无法解析则返回 None。
    """
    from fund_estimator.fund_estimator_index_agent import (
        query_db_fund_info,
        resolve_index_symbol,
    )

    db_info = query_db_fund_info(fund_code)
    if db_info and db_info.is_passive and db_info.tracker_index_code:
        return resolve_index_symbol(db_info.tracker_index, db_info.tracker_index_code)
    return None


def run(
    method: str,
    start: str,
    end: str,
    fund_code: str = FUND_CODE,
    force: bool = False,
    index_symbol: Optional[str] = None,
) -> dict:
    """执行多天批量回测。

    Parameters
    ----------
    index_symbol : str, optional
        目标指数 symbol。None 时先查 DB 自动检测；仍为 None 则 fallback 到 sz399006。
    """
    # 解析目标指数
    resolved_symbol = index_symbol or _detect_index_symbol(fund_code) or DEFAULT_INDEX_SYMBOL

    need_stocks = method in ("v_top10", "v_index_blend", "v_residual_uncovered")
    inputs = load_common_inputs(
        fund_code, start, end,
        with_holdings=True, with_stocks=need_stocks, force=force,
        index_symbol=resolved_symbol,
    )
    result = backtest_range(inputs, method, start, end)
    stats = result.stats()
    stats["label"] = METHOD_LABELS.get(method, method)
    stats["index_symbol_used"] = inputs.index_symbol

    # 落盘每日误差
    cdir = cache_dir()
    daily_path = os.path.join(cdir, f"batch_{method}_{inputs.index_symbol}_{start}_{end}.csv")
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
    parser.add_argument("--index-symbol", default=None,
                        help="目标指数 symbol，如 sz399006 / sh000300；默认从 DB 自动检测")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args(argv)

    stats = run(args.method, args.start, args.end, args.fund,
                force=args.force, index_symbol=args.index_symbol)
    print(json.dumps(stats, ensure_ascii=False, indent=2))
    if stats.get("n", 0):
        print(f"\n阈值 {THRESHOLD_PP}pp：超阈值 {stats['over_ratio']}，"
              f"MAE={stats['mae_pp']}pp，MAX={stats['max_pp']}pp")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
