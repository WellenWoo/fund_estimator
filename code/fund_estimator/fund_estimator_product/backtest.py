"""商品/商品期货基金回测模块。

设计
----
**与 ITERATIONS §1 相同的回测骨架**，但输入侧改为商品 LOF 专用：

1. 预取：
   - 基金历史 NAV（change_pct 列即为 T-1 涨跌%）
   - 不再需要指数日线 / 成分股日线（商品 LOF 没有指数）
2. 构造 trading_days：有 NAV 的日期集合（升序）
3. 逐日估值：
   - T-1 = 上一交易日，T-1 涨跌% = nav_rows[t-1].change_pct
   - 调用 estimators.estimate(method, t1_change_pct=...)
   - 与 nav_rows[t].nav 组成 NAVComparison
4. 聚合：MAE / RMSE / MAX / Mean / over_threshold

为什么是「T-1 涨跌代理」而不是「指数代理」？
- 商品 LOF 没有指数；
- 品种期货历史 K 线公开 API 在当前网络环境受限（已在开发日志中说明）；
- **基金官方每日公布的 T-1 涨跌%** 本身就是「T-1 当日底层品种涨跌的
  精确观测」（按 fund_estimator_product.commodity_map.beta=1.0 假设）。
  因此 T 日预测 = T-1 涨跌% 是一个合理的"动量代理"，与
  ITERATIONS §1 中 v_index_full 思路一致（用"昨日观测"代理"今日"）。
"""

from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass, field
from typing import Optional

# --- import 引导：确保能 import fund_estimator.* ---------------------------- #
_THIS = os.path.dirname(os.path.abspath(__file__))
_CODE_ROOT = os.path.dirname(os.path.dirname(_THIS))   # code/fund_estimator/
if _CODE_ROOT not in sys.path:
    sys.path.insert(0, _CODE_ROOT)

from fund_estimator.core.models import NAVComparison, THRESHOLD_PP  # noqa: E402
from fund_estimator.data_sources.cache import CsvCache  # noqa: E402
from fund_estimator.data_sources.eastmoney.nav_history import fetch_nav_history  # noqa: E402

from .commodity_map import CommodityInfo, COMMODITY_MAP  # noqa: E402
from .estimators import estimate, DEFAULT_METHOD, METHODS  # noqa: E402


# --------------------------------------------------------------------------- #
# 共享输入
# --------------------------------------------------------------------------- #
@dataclass
class CommonInputs:
    """一次商品基金回测所需的全部预取数据。"""

    fund_code: str
    commodity: CommodityInfo
    nav_rows: list[dict]                 # 升序 [{date, nav, acc_nav, change_pct}, ...]
    nav_map: dict[str, float]            # date -> nav
    trading_days: list[str]              # 有 NAV 的交易日（升序）
    t1_change_map: dict[str, float]      # date -> 该日官方 change_pct（即"昨日涨跌%"）


def load_common_inputs(
    fund_code: str,
    start: str = "",
    end: str = "",
    *,
    cache: Optional[CsvCache] = None,
    force: bool = False,
) -> CommonInputs:
    """预取商品基金回测所需数据。

    Raises
    ------
    KeyError
        当基金代码不在 ``COMMODITY_MAP`` 中。
    """
    cache = cache or CsvCache()
    if fund_code not in COMMODITY_MAP:
        raise KeyError(
            f"fund {fund_code} not in COMMODITY_MAP. supported: {list(COMMODITY_MAP)}"
        )
    commodity = COMMODITY_MAP[fund_code]

    nav_rows = fetch_nav_history(fund_code, start, end, cache=cache, force=force)
    nav_map = {r["date"]: r["nav"] for r in nav_rows}

    tdays = [
        r["date"]
        for r in nav_rows
        if (not start or r["date"] >= start) and (not end or r["date"] <= end)
    ]

    # 构造 T-1 涨跌% 表：date -> change_pct (即该日当天的官方涨跌%)
    # 因为商品基金 NAV 在 T-1 21:00 公布，所以 T 日 9:30 已知。
    t1_change_map: dict[str, float] = {}
    for r in nav_rows:
        try:
            t1_change_map[r["date"]] = float(r.get("change_pct") or 0.0)
        except (TypeError, ValueError):
            t1_change_map[r["date"]] = 0.0

    return CommonInputs(
        fund_code=fund_code,
        commodity=commodity,
        nav_rows=nav_rows,
        nav_map=nav_map,
        trading_days=tdays,
        t1_change_map=t1_change_map,
    )


# --------------------------------------------------------------------------- #
# 单日估值
# --------------------------------------------------------------------------- #
def _prev_trading_day(tdays: list[str], today: str) -> Optional[str]:
    prev = None
    for d in tdays:
        if d < today:
            prev = d
        elif d == today:
            return prev
        else:
            break
    return prev


def estimate_for_day(
    inputs: CommonInputs,
    today: str,
    method: str,
    *,
    futures_change_pct: Optional[float] = None,
    beta_override: Optional[float] = None,
    fee_drag_pp_override: Optional[float] = None,
) -> Optional[NAVComparison]:
    """对单个交易日做商品基金估值 + 对比。

    Parameters
    ----------
    method:
        5 种算法之一。
    futures_change_pct:
        仅 ``v_futures`` 必需。
    beta_override / fee_drag_pp_override:
        测试时手动覆盖 COMMODITY_MAP 默认值。
    """
    if today not in inputs.nav_map:
        return None  # 非交易日

    t1 = _prev_trading_day(inputs.trading_days, today)
    if not t1:
        return None  # 第一天没有 T-1
    t1_nav = inputs.nav_map.get(t1)
    if not t1_nav:
        return None

    t1_change = inputs.t1_change_map.get(t1)

    beta = beta_override if beta_override is not None else inputs.commodity.beta
    fee_drag = (
        fee_drag_pp_override
        if fee_drag_pp_override is not None
        else inputs.commodity.fee_drag_pp
    )

    est = estimate(
        method,
        fund_code=inputs.fund_code,
        today=today,
        t1_date=t1,
        t1_nav=t1_nav,
        t1_change_pct=t1_change,
        futures_change_pct=futures_change_pct,
        beta=beta,
        fee_drag_pp=fee_drag,
    )

    official_nav = inputs.nav_map.get(today)
    official_change = None
    if official_nav and t1_nav > 0:
        official_change = (official_nav - t1_nav) / t1_nav * 100.0

    return NAVComparison(
        estimate=est,
        official_nav=official_nav,
        official_change_pct=official_change,
    )


# --------------------------------------------------------------------------- #
# 回测聚合
# --------------------------------------------------------------------------- #
@dataclass
class BacktestResult:
    method: str
    start: str
    end: str
    comparisons: list[NAVComparison]
    commodity: Optional[CommodityInfo] = None

    @property
    def valid(self) -> list[NAVComparison]:
        return [c for c in self.comparisons if c.error_pp is not None]

    def stats(self) -> dict:
        errs = [c.error_pp for c in self.valid]
        n = len(errs)
        if n == 0:
            return {"method": self.method, "n": 0}
        mae = sum(abs(e) for e in errs) / n
        rmse = (sum(e * e for e in errs) / n) ** 0.5
        mean = sum(errs) / n
        mx = max(abs(e) for e in errs)
        over = sum(1 for e in errs if abs(e) > THRESHOLD_PP)
        return {
            "method": self.method,
            "method_label": None,
            "fund_code": self.commodity.fund_code if self.commodity else "",
            "fund_name": self.commodity.fund_name if self.commodity else "",
            "commodity": self.commodity.commodity if self.commodity else "",
            "symbol": self.commodity.symbol if self.commodity else "",
            "start": self.start,
            "end": self.end,
            "n": n,
            "mae_pp": round(mae, 4),
            "rmse_pp": round(rmse, 4),
            "mean_pp": round(mean, 4),
            "max_pp": round(mx, 4),
            "over_threshold": over,
            "over_ratio": f"{over}/{n}",
        }


def backtest_range(
    inputs: CommonInputs,
    method: str,
    start: str,
    end: str,
) -> BacktestResult:
    """在 [start, end] 区间内对单一方法回测。"""
    comps: list[NAVComparison] = []
    for today in inputs.trading_days:
        if start and today < start:
            continue
        if end and today > end:
            continue
        c = estimate_for_day(inputs, today, method)
        if c is not None:
            comps.append(c)
    return BacktestResult(
        method=method, start=start, end=end, comparisons=comps,
        commodity=inputs.commodity,
    )


def backtest_all_methods(
    inputs: CommonInputs,
    start: str,
    end: str,
    *,
    include_v_futures: bool = False,
) -> dict[str, BacktestResult]:
    """对所有算法一次性回测，返回 {method: BacktestResult}。

    v_futures 在纯回测场景下**不可用**（无历史期货 K 线），
    需在 include_v_futures=True 且调用方提供 futures_change 时
    才能跑。本函数默认排除 v_futures，调用方要单独跑 v_futures
    可走 ``backtest_range`` 手动传 futures_change。
    """
    out: dict[str, BacktestResult] = {}
    methods = list(METHODS)
    if not include_v_futures:
        methods = [m for m in methods if m != "v_futures"]
    for m in methods:
        out[m] = backtest_range(inputs, m, start, end)
    return out


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def main(argv: Optional[list[str]] = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
    parser = argparse.ArgumentParser(description="商品基金回测入口（5 种算法横向对比）")
    parser.add_argument("--fund", required=True, help="商品基金代码（如 161226）")
    parser.add_argument("--method", default=None, choices=METHODS + [None],
                        help="指定单一算法；不指定则跑全部")
    parser.add_argument("--start", default="")
    parser.add_argument("--end", default="")
    parser.add_argument("--force", action="store_true", help="忽略缓存强制重取 NAV")
    args = parser.parse_args(argv)

    inputs = load_common_inputs(args.fund, args.start, args.end, force=args.force)
    start = args.start or (inputs.trading_days[0] if inputs.trading_days else "")
    end = args.end or (inputs.trading_days[-1] if inputs.trading_days else "")

    if args.method:
        result = backtest_range(inputs, args.method, start, end)
        stats = result.stats()
    else:
        results = backtest_all_methods(inputs, start, end)
        stats = {
            "fund": inputs.commodity.fund_code,
            "fund_name": inputs.commodity.fund_name,
            "commodity": inputs.commodity.commodity,
            "symbol": inputs.commodity.symbol,
            "start": start,
            "end": end,
            "per_method": [r.stats() for r in results.values()],
        }
    import json
    print(json.dumps(stats, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "CommonInputs",
    "BacktestResult",
    "load_common_inputs",
    "estimate_for_day",
    "backtest_range",
    "backtest_all_methods",
]
