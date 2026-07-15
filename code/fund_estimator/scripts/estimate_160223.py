"""单次估值 CLI（实时盘中）—— scripts/estimate_160223.py。

README §3.1 的「实时盘中」版本：
- 从天天基金拿 T-1 单位净值 (dwjz) 作为基线；
- 从新浪/腾讯拿创业板指实时点位算涨跌%（或用持仓还原）；
- 输出估算 NAV，并可与天天基金官方估值 (gsz) 交叉校验。

用法::

    python code/fund_estimator/scripts/estimate_160223.py --method v_index_full_no_cash
    python code/fund_estimator/scripts/estimate_160223.py --method v_top10 --cross-check
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

from fund_estimator.data_sources.cache import CsvCache  # noqa: E402
from fund_estimator.data_sources.eastmoney.holdings_full import fetch_full_holdings  # noqa: E402
from fund_estimator.data_sources.sina.realtime import fetch_realtime as fetch_sina  # noqa: E402
from fund_estimator.data_sources.tencent.realtime import fetch_realtime as fetch_tencent  # noqa: E402
from fund_estimator.data_sources.tiantian import fetch_official_estimate  # noqa: E402
from fund_estimator.estimators.holdings_based import (  # noqa: E402
    estimate,
    CYB_INDEX,
    DEFAULT_METHOD,
    METHODS,
)

FUND_CODE = "160223"


def _fetch_quotes(codes: list[str]) -> dict:
    """新浪优先，失败降级腾讯（README §10 多源容灾）。"""
    try:
        q = fetch_sina(codes)
        if q:
            return q
    except Exception:  # noqa: BLE001
        pass
    try:
        return fetch_tencent(codes)
    except Exception:  # noqa: BLE001
        return {}


def run(method: str, fund_code: str = FUND_CODE, cross_check: bool = False) -> dict:
    cache = CsvCache()

    # 1. 基线：天天基金官方估值给出 T-1 净值(dwjz)
    official = fetch_official_estimate(fund_code)
    if not official or official.dwjz <= 0:
        raise RuntimeError("无法获取 T-1 单位净值（天天基金 fundgz 接口）")
    t1_nav = official.dwjz
    t1_date = official.jzrq
    today = (official.gztime or "")[:10] or ""

    # 2. 行情
    need_stocks = method in ("v_top10", "v_index_blend", "v_residual_uncovered")
    holdings = []
    quotes_today: dict = {}
    codes = [CYB_INDEX]
    if need_stocks:
        full = fetch_full_holdings(fund_code, cache=cache)
        holdings = full.holdings
        codes += [h.secid for h in holdings]

    quotes = _fetch_quotes(codes)
    quotes_today = quotes

    index_change_pct = None
    idx = quotes.get(CYB_INDEX)
    if idx:
        index_change_pct = idx.change_pct

    # 3. 估值
    est = estimate(
        method,
        fund_code=fund_code,
        today=today,
        t1_date=t1_date,
        t1_nav=t1_nav,
        index_change_pct=index_change_pct,
        holdings=holdings,
        quotes_today=quotes_today,
        quotes_t1={},  # 实时场景用 quote.prev_close 作为 T-1 价
    )

    out = est.to_dict()
    if cross_check and official:
        out["tiantian_official_gsz"] = official.gsz
        out["tiantian_official_gszzl"] = official.gszzl
        if official.gsz > 0:
            out["diff_vs_official_gsz"] = round(est.estimated_nav - official.gsz, 4)
    return out


def main(argv: Optional[list[str]] = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
    parser = argparse.ArgumentParser(description="LOF 160223 单次实时估值")
    parser.add_argument("--method", default=DEFAULT_METHOD, choices=METHODS)
    parser.add_argument("--fund", default=FUND_CODE)
    parser.add_argument("--cross-check", action="store_true", help="与天天基金官方估值交叉校验")
    args = parser.parse_args(argv)

    result = run(args.method, args.fund, cross_check=args.cross_check)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
