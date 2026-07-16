"""CLI: 对 LOF 160223 做一次实时估值。

用法:
    python -m fund_estimator.scripts.estimate_160223 [--last-nav 2.2247]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# 让脚本可以直接 `python scripts/estimate_160223.py` 运行
ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

from fund_estimator.data_sources.eastmoney.holding import fetch_top_holdings  # noqa: E402
from fund_estimator.data_sources.sina.realtime import build_symbol, fetch_quotes  # noqa: E402
from fund_estimator.estimators.holdings_based import (  # noqa: E402
    WeightPolicy,
    estimate_nav,
)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--fund-code", default="160223")
    parser.add_argument(
        "--last-nav",
        type=float,
        default=None,
        help="最近一次官方净值（T-1 公布）；不传时从天天基金拉",
    )
    parser.add_argument("--top-n", type=int, default=10)
    args = parser.parse_args()

    holding = fetch_top_holdings(args.fund_code, top_n=args.top_n)
    print(f"[1/3] 基金: {holding.fund_name} ({holding.fund_code})")
    print(f"      股票仓位: {holding.stock_position_pct}%")
    print(f"      持仓股票: {[p.code for p in holding.stock_positions]}")

    if not holding.stock_positions:
        print("无持仓数据，退出")
        return 1

    symbols = [build_symbol(p.market, p.code) for p in holding.stock_positions]
    quotes = fetch_quotes(symbols)
    print(f"[2/3] 拉取实时行情: {len(quotes)}/{len(symbols)} 成功")
    for q in quotes:
        print(f"      {q.market}{q.code} {q.name} 现价={q.price} 涨跌={q.change_pct:.2f}%")

    if args.last_nav is None:
        # 默认拉天天基金当下 T-1 的单位净值
        import urllib.request
        import urllib.parse
        import re
        url = f"https://fundgz.1234567.com.cn/js/{args.fund_code}.js"
        with urllib.request.urlopen(url, timeout=10) as resp:
            raw = resp.read().decode("utf-8", errors="ignore")
        m = re.search(r'"dwjz":"([\d.]+)"', raw)
        last_nav = float(m.group(1)) if m else 1.0
        print(f"      最近官方净值(T-1)={last_nav}（从天天基金拉取）")
    else:
        last_nav = args.last_nav
        print(f"      最近官方净值(T-1)={last_nav}（来自 --last-nav）")

    nav = estimate_nav(holding, quotes, last_nav, WeightPolicy())
    print(f"[3/3] 估算结果:")
    print(json.dumps(nav.to_dict(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
