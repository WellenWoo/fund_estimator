"""债基估值模块 CLI 入口。

用法::

    # 单日实时盘中估值
    python -m fund_estimator_bond --fund 164703 --date 2026-07-25

    # 批量回测（横向对比 5 种方法）
    python -m fund_estimator_bond --fund 164703 --backtest --start 2026-04-27 --end 2026-07-23

    # JSON 输出
    python -m fund_estimator_bond --fund 164703 --backtest --json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime

_THIS = os.path.dirname(os.path.abspath(__file__))
_CODE_ROOT = os.path.dirname(os.path.dirname(_THIS))   # code/fund_estimator/
if _CODE_ROOT not in sys.path:
    sys.path.insert(0, _CODE_ROOT)

from .bond_map import list_supported_funds  # noqa: E402
from .realtime import estimate_bond_realtime, print_result  # noqa: E402
from .backtest import backtest_all_methods, backtest_range, load_common_inputs, METHODS, METHOD_LABELS  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    parser = argparse.ArgumentParser(
        description="Bond Fund Real-time Estimator / Backtest CLI",
    )
    parser.add_argument("--fund", help="6 位债基代码")
    parser.add_argument("--date", help="估值日 YYYY-MM-DD，默认今天")
    parser.add_argument("--method", default=None, help="算法（默认自动）")
    parser.add_argument("--backtest", action="store_true", help="批量回测模式")
    parser.add_argument("--start", default="", help="回测起始日")
    parser.add_argument("--end", default="", help="回测结束日")
    parser.add_argument("--force", action="store_true", help="强制重拉数据")
    parser.add_argument("--json", action="store_true", help="仅输出 JSON")
    parser.add_argument("--list", action="store_true", help="列出已支持的债基")
    args = parser.parse_args(argv)

    if args.list:
        print("已注册债基:")
        for c in list_supported_funds():
            print(f"  {c}")
        return 0

    if not args.fund:
        parser.print_help()
        return 1

    if args.backtest:
        if args.method:
            # 单方法回测
            inputs = load_common_inputs(args.fund, args.start, args.end, force=args.force)
            r = backtest_range(inputs, args.method, args.start, args.end)
            if args.json:
                print(json.dumps(r.to_dict(), ensure_ascii=False, indent=2))
            else:
                print(f"\n=== 债基回测 {args.fund} ({r.method_label}) ===")
                print(f"区间: {args.start or '默认'} ~ {args.end or '默认'}")
                print(f"  N={r.n}  MAE={r.mae:.4f}  RMSE={r.rmse:.4f}  "
                      f"MAX={r.max_err:.4f}  MeanErr={r.mean_err:+.4f}  "
                      f"Over={r.over_threshold}/{r.n}")
            return 0
        else:
            # 全部方法横向对比
            results = backtest_all_methods(args.fund, args.start, args.end, force=args.force)
            if args.json:
                print(json.dumps([r.to_dict() for r in results], ensure_ascii=False, indent=2))
                return 0
            print(f"\n=== 债基回测 {args.fund}（全部方法）===")
            print(f"区间: {args.start or '默认'} ~ {args.end or '默认'}\n")
            print(f"{'方法':<32}{'N':>4}{'MAE':>9}{'RMSE':>9}{'MAX':>9}{'MeanErr':>10}{'Over':>9}")
            print("-" * 84)
            for r in results:
                print(f"{r.method_label:<32}"
                      f"{r.n:>4d}"
                      f"{r.mae:>9.4f}"
                      f"{r.rmse:>9.4f}"
                      f"{r.max_err:>9.4f}"
                      f"{r.mean_err:>+10.4f}"
                      f"{r.over_threshold:>5d}/{r.n}")
            return 0

    # 单日实时估值
    trade_date = args.date or datetime.now().strftime("%Y-%m-%d")
    result = estimate_bond_realtime(args.fund, trade_date, method=args.method, force=args.force)
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print_result(result)
    return 0 if result.get("success") else 1


if __name__ == "__main__":
    raise SystemExit(main())
