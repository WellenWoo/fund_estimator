"""每日盘后生产脚本 —— scripts/daily_close_estimate.py。

README §3.1 的示例入口。用某个交易日的**收盘**行情估值，可选 --fetch-official
去抓当日官方 NAV 做对比（注意 README §9：官方 NAV 21:00 才公布）。

自动检测逻辑：
- 如果 --index-symbol 未指定，则从 lof_info.db 查询该基金的 tracker_index_code，
  自动解析为对应指数 symbol（如 sh000300 for 沪深300, sz399006 for 创业板指）。
- 如果数据库中无该基金，fallback 到 sz399006（兼容旧用法）。

用法::

    python code/fund_estimator/scripts/daily_close_estimate.py \
        --method v_index_full_no_cash --trade-date 2026-07-13 --fetch-official

    # 指定指数
    python code/fund_estimator/scripts/daily_close_estimate.py \
        --fund 160615 --index-symbol sh000300 --trade-date 2026-07-13
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Optional

_THIS = os.path.dirname(os.path.abspath(__file__))
_CODE_ROOT = os.path.dirname(os.path.dirname(_THIS))
if _CODE_ROOT not in sys.path:
    sys.path.insert(0, _CODE_ROOT)

# 延迟导入 fund_estimator_index_agent 的数据库查询函数，避免循环依赖
from fund_estimator.backtest.run_backtest import (  # noqa: E402
    load_common_inputs,
    estimate_for_day,
    FUND_CODE,
)
from fund_estimator.estimators.holdings_based import DEFAULT_METHOD, METHODS  # noqa: E402


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
    trade_date: str,
    fund_code: str = FUND_CODE,
    fetch_official: bool = False,
    force: bool = False,
    index_symbol: Optional[str] = None,
) -> dict:
    """执行单日估值。

    Parameters
    ----------
    index_symbol : str, optional
        目标指数 symbol。None 时先查 DB 自动检测；仍为 None 则 fallback 到 sz399006。
    """
    # 解析目标指数
    resolved_symbol = index_symbol or _detect_index_symbol(fund_code) or DEFAULT_INDEX_SYMBOL

    need_stocks = method in ("v_top10", "v_index_blend", "v_residual_uncovered")
    # 取足够长的历史区间以确保 trade_date 的 T-1 在内
    inputs = load_common_inputs(
        fund_code, "", "",
        with_holdings=True, with_stocks=need_stocks, force=force,
        index_symbol=resolved_symbol,
    )
    comp = estimate_for_day(inputs, trade_date, method)
    if comp is None:
        raise RuntimeError(f"{trade_date} 非交易日或数据缺失，无法估值")

    est = comp.estimate
    out = {
        "fund_code": est.fund_code,
        "today": est.today,
        "t1_date": est.t1_date,
        "t1_nav": est.t1_nav,
        "estimated_nav": est.estimated_nav,
        "estimated_change_pct": est.estimated_change_pct,
        "method": est.method,
        "index_symbol_used": inputs.index_symbol,
    }
    if fetch_official and comp.official_nav is not None:
        out["official_nav"] = comp.official_nav
        out["official_change_pct"] = round(comp.official_change_pct, 4) if comp.official_change_pct is not None else None
        out["abs_error"] = round(comp.abs_error, 6)
        out["error_pp"] = round(comp.error_pp, 4)
        out["over_threshold"] = comp.over_threshold
    return out


def main(argv: Optional[list[str]] = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
    parser = argparse.ArgumentParser(description="每日盘后估值（单日）")
    parser.add_argument("--method", default=DEFAULT_METHOD, choices=METHODS)
    parser.add_argument("--trade-date", required=True)
    parser.add_argument("--fund", default=FUND_CODE)
    parser.add_argument("--index-symbol", default=None,
                        help="目标指数 symbol，如 sz399006 / sh000300；默认从 DB 自动检测")
    parser.add_argument("--fetch-official", action="store_true")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args(argv)

    result = run(
        args.method, args.trade_date, args.fund,
        fetch_official=args.fetch_official, force=args.force,
        index_symbol=args.index_symbol,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if "official_nav" in result:
        diff = result["estimated_nav"] - result["official_nav"]
        pct = diff / result["official_nav"] * 100 if result["official_nav"] else 0
        print(f"\n对比官方 NAV {result['official_nav']}: "
              f"差异 {diff:+.4f} ({pct:+.4f}%)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
