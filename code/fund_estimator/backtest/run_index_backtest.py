"""创业板指代理回测 —— 专注 v_index_full / v_index_full_no_cash 两个指数系算法。

这是 README §5「创业板指全代理」路径的独立回测入口。相较 run_backtest.py：
- 无需抓成分股日线（只用基金 NAV + 创业板指日线），跑得更快；
- 默认同时对比「含 cash_drag」与「无 cash_drag」两版，验证 ITERATIONS.md
  Iteration 2 的结论：去掉 cash_drag 后 bias 从 -0.096 → +0.004。
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

from fund_estimator.backtest.run_backtest import (  # noqa: E402
    load_common_inputs,
    backtest_range,
    BacktestResult,
    FUND_CODE,
)
from fund_estimator.estimators.holdings_based import METHOD_LABELS  # noqa: E402


INDEX_METHODS = ["v_index_full", "v_index_full_no_cash"]


def backtest_index_range(
    fund_code: str = FUND_CODE,
    start: str = "2026-04-25",
    end: str = "2026-07-14",
    *,
    methods: Optional[list[str]] = None,
    force: bool = False,
) -> list[BacktestResult]:
    """对指数系算法批量回测。"""
    methods = methods or INDEX_METHODS
    inputs = load_common_inputs(
        fund_code, start, end,
        with_holdings=False, with_stocks=False, force=force,
    )
    results = []
    for m in methods:
        results.append(backtest_range(inputs, m, start, end))
    return results


def main(argv: Optional[list[str]] = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")  # 兼容 Windows GBK 控制台
    except Exception:  # noqa: BLE001
        pass
    parser = argparse.ArgumentParser(description="创业板指代理回测")
    parser.add_argument("--fund", default=FUND_CODE)
    parser.add_argument("--start", default="2026-04-25")
    parser.add_argument("--end", default="2026-07-14")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args(argv)

    results = backtest_index_range(args.fund, args.start, args.end, force=args.force)
    out = []
    for r in results:
        s = r.stats()
        s["label"] = METHOD_LABELS.get(r.method, r.method)
        out.append(s)
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
