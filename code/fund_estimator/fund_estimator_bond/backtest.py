"""债基估值回测模块。

设计
====
**与 ITERATIONS §1 相同的回测骨架**，但输入侧改为债基专用：
1. 预取：
   - 基金历史 NAV（含 change_pct 列）— 即 T-1 涨跌%
   - 主代理指数历史 K 线（sh000061 / sh000012）— 即代理指数日涨跌%
2. 构造 ``trading_days``：有 NAV 的日期集合（升序）
3. 逐日估算：
   - T-1 = 上一交易日，T-1 涨跌% = nav_rows[t-1].change_pct
   - 主代理指数 T 涨跌% = bond_index_klines[T].change_pct
   - 调用 ``estimators.estimate(method, ...)``
   - 与 ``nav_rows[T].nav`` 组成 NAVComparison
4. 聚合：MAE / RMSE / MAX / Mean / over_threshold

为什么不用「持仓还原 + 指数长尾」？
=================================
债基季报披露的「前 5 大持仓」是债券代码，公开市场虽能取 K 线，但
- 单只券流动性差，K 线含大量「无成交」日，噪声极大；
- 久期 / 票息 / 信用利差难以用统一 K 线表达；
- 实测发现，对纯债基，**单一公开债券指数代理**（沪深企业债 / 上证国债）的
  误差已 < 0.05pp，已突破噪声底线，再叠加持仓还原反而引入更多不确定性。
  因此本模块默认**只走「指数代理」路线**。
"""

from __future__ import annotations

import argparse
import json
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
from fund_estimator.data_sources.cache import CsvCache, http_get  # noqa: E402
from fund_estimator.data_sources.eastmoney.nav_history import fetch_nav_history  # noqa: E402
from fund_estimator.data_sources.sina.history import fetch_kline  # noqa: E402

from .bond_map import BondInfo, get_bond_info_for_fund  # noqa: E402
from .estimators import estimate, DEFAULT_METHOD, METHODS, METHOD_LABELS  # noqa: E402


# ---------------------------------------------------------------------------
# 公共输入
# ---------------------------------------------------------------------------
@dataclass
class CommonInputs:
    """一次债基回测所需的全部预取数据。"""

    fund_code: str
    bond_info: BondInfo
    nav_rows: list[dict]                 # 升序 [{date, nav, acc_nav, change_pct}, ...]
    nav_map: dict[str, float]            # date -> nav
    trading_days: list[str]              # 有 NAV 的交易日（升序）
    t1_change_map: dict[str, float]      # date -> 该日官方 change_pct（即「昨日涨跌%」）
    primary_index_klines: dict[str, dict]  # date -> {open, close, high, low, change_pct}
    secondary_index_klines: dict[str, dict]  # date -> {open, close, high, low, change_pct}


def _build_index_change_map(klines: list[dict]) -> dict[str, dict]:
    """从 sina K 线构造 date -> {close, prev_close, change_pct} 字典。

    注意：``fetch_kline`` 返回的是**升序**（最早在前），所以
    每行 K 线的「前一日 close」是 ``klines[i-1].close``。
    """
    out: dict[str, dict] = {}
    for i, row in enumerate(klines):
        if i > 0:
            prev = klines[i - 1]
            prev_close = float(prev.get("close", 0) or 0)
            cur_close = float(row.get("close", 0) or 0)
            chg = (cur_close - prev_close) / prev_close * 100.0 if prev_close > 0 else 0.0
        else:
            # 最早一行没有 prev，self-self = 0
            prev_close = float(row.get("close", 0) or 0)
            cur_close = prev_close
            chg = 0.0
        out[row["date"]] = {
            "open": float(row.get("open", 0) or 0),
            "close": cur_close,
            "high": float(row.get("high", 0) or 0),
            "low": float(row.get("low", 0) or 0),
            "prev_close": prev_close,
            "change_pct": round(chg, 6),
        }
    return out


def load_common_inputs(
    fund_code: str,
    start: str = "",
    end: str = "",
    *,
    cache: Optional[CsvCache] = None,
    force: bool = False,
) -> CommonInputs:
    """预取债基回测所需数据。

    Parameters
    ----------
    fund_code : str
        6 位债基代码（必须在 ``BOND_MAP`` 中）。
    start, end : str
        区间端点（YYYY-MM-DD），留空取默认近 60 个交易日。
    cache : CsvCache, optional
    force : bool
        是否强制重新拉取。
    """
    cache = cache or CsvCache()
    bond_info = get_bond_info_for_fund(fund_code)
    if bond_info is None:
        raise ValueError(
            f"基金 {fund_code} 不在 BOND_MAP 中，请先在 bond_map.py 注册。"
        )

    # 1) NAV 历史
    nav_rows = fetch_nav_history(fund_code, start, end, cache=cache, force=force)
    # 升序
    nav_rows = sorted(nav_rows, key=lambda r: r["date"])
    nav_map = {r["date"]: float(r["nav"]) for r in nav_rows}
    trading_days = [r["date"] for r in nav_rows]

    # 2) 主 / 辅助代理指数 K 线 — 一次性取 1023 个交易日（覆盖 ~4 年），
    #    后续按 date 查表即可，无需 start/end 参数。
    #    注意：cache key 只跟 symbol 有关，与 datalen 无关，因此如果之前
    #    用 datalen=10 拉过导致缓存只存了 5 条，本函数必须 force=True 才能
    #    拉到完整 1023 条。
    prim_klines = fetch_kline(bond_info.primary_index[0], datalen=1023,
                              cache=cache, force=force)
    sec_klines = fetch_kline(bond_info.secondary_index[0], datalen=1023,
                             cache=cache, force=force)

    # 3) 构造 T-1 change map（= 自身 NAV 的 change_pct）
    t1_change_map: dict[str, float] = {}
    for r in nav_rows:
        try:
            t1_change_map[r["date"]] = float(r.get("change_pct", 0) or 0)
        except (TypeError, ValueError):
            t1_change_map[r["date"]] = 0.0

    return CommonInputs(
        fund_code=fund_code,
        bond_info=bond_info,
        nav_rows=nav_rows,
        nav_map=nav_map,
        trading_days=trading_days,
        t1_change_map=t1_change_map,
        primary_index_klines=_build_index_change_map(prim_klines or []),
        secondary_index_klines=_build_index_change_map(sec_klines or []),
    )


def _shift_date(date_str: str, days: int) -> str:
    """YYYY-MM-DD 加减 N 天。"""
    from datetime import datetime, timedelta
    dt = datetime.strptime(date_str, "%Y-%m-%d")
    return (dt + timedelta(days=days)).strftime("%Y-%m-%d")


# ---------------------------------------------------------------------------
# 单日估算
# ---------------------------------------------------------------------------
def estimate_for_day(
    inputs: CommonInputs,
    trade_date: str,
    method: str,
    *,
    beta: Optional[float] = None,
    fee_drag_pp: Optional[float] = None,
    use_secondary: Optional[bool] = None,
) -> Optional[NAVComparison]:
    """估算单日 NAV 并与官方 NAV 对比。

    Parameters
    ----------
    inputs : CommonInputs
    trade_date : str
        T 日。
    method : str
        算法标识。 ``v_bond_sse_gov`` 会自动使用 secondary_index（国债指数），
        其余 csi_corp / t1_persist / random_walk / blend 使用 primary_index。
    beta : float, optional
        覆盖 bond_info.beta（用于灵敏度测试）。
    fee_drag_pp : float, optional
        覆盖 bond_info.fee_drag_pp。
    use_secondary : bool, optional
        True/False 强制选择 primary/secondary；None 时按 method 自动决定。
    """
    if trade_date not in inputs.nav_map:
        return None
    t1 = _prev_trading_day(inputs.trading_days, trade_date)
    if not t1:
        return None
    t1_nav = inputs.nav_map[t1]
    if t1_nav <= 0:
        return None

    t1_change = inputs.t1_change_map.get(t1, 0.0)

    # 默认按 method 决定用 primary / secondary
    if use_secondary is None:
        use_secondary = (method == "v_bond_sse_gov")

    if use_secondary:
        idx_map = inputs.secondary_index_klines
    else:
        idx_map = inputs.primary_index_klines
    idx_row = idx_map.get(trade_date) or idx_map.get(_shift_date(trade_date, -1))
    bond_idx_change = idx_row["change_pct"] if idx_row else 0.0

    actual_beta = beta if beta is not None else inputs.bond_info.beta
    actual_fee = fee_drag_pp if fee_drag_pp is not None else inputs.bond_info.fee_drag_pp

    est = estimate(
        method,
        fund_code=inputs.fund_code,
        today=trade_date,
        t1_date=t1,
        t1_nav=t1_nav,
        t1_change_pct=t1_change,
        bond_index_change_pct=bond_idx_change,
        beta=actual_beta,
        fee_drag_pp=actual_fee,
        detail={
            "primary_index": inputs.bond_info.primary_index[0],
            "secondary_index": inputs.bond_info.secondary_index[0],
            "used_index": ("secondary" if use_secondary else "primary"),
            "primary_index_change_pct": (bond_idx_change if use_secondary
                                          else (idx_map.get(trade_date) or {}).get("change_pct")),
            "secondary_index_change_pct": ((idx_map.get(trade_date) or {}).get("change_pct")
                                            if use_secondary else None),
        },
    )
    official = inputs.nav_map[trade_date]
    return NAVComparison(estimate=est, official_nav=official)


def _prev_trading_day(trading_days: list[str], trade_date: str) -> Optional[str]:
    """给定 T 日返回 T-1（最大 trading_day < trade_date）。"""
    prev = None
    for d in trading_days:
        if d < trade_date:
            prev = d
        else:
            break
    return prev


# ---------------------------------------------------------------------------
# 批量回测
# ---------------------------------------------------------------------------
@dataclass
class BacktestResult:
    """单方法的回测聚合结果。"""

    fund_code: str
    method: str
    method_label: str
    n: int
    mae: float
    rmse: float
    max_err: float
    mean_err: float
    bias: float              # = mean_err（PP 量纲）
    over_threshold: int
    threshold_pp: float
    rows: list[dict] = field(default_factory=list)
    skipped_jump_days: int = 0    # 因 NAV 跳变（分红/拆分）跳过的天数

    def to_dict(self) -> dict:
        return {
            "fund_code": self.fund_code,
            "method": self.method,
            "method_label": self.method_label,
            "n": self.n,
            "skipped_jump_days": self.skipped_jump_days,
            "mae": round(self.mae, 4),
            "rmse": round(self.rmse, 4),
            "max_err": round(self.max_err, 4),
            "mean_err": round(self.mean_err, 4),
            "bias": round(self.bias, 4),
            "over_threshold": self.over_threshold,
            "threshold_pp": self.threshold_pp,
        }


def backtest_range(
    inputs: CommonInputs,
    method: str,
    start: str = "",
    end: str = "",
    *,
    skip_jump_threshold_pct: float = 5.0,
) -> BacktestResult:
    """对单一方法在 [start, end] 内做回测。

    Notes
    -----
    start/end 是**估值日 T**的区间（含端点），不是 T-1。
    若 |NAV_T / NAV_{T-1} - 1| > ``skip_jump_threshold_pct``，视为分红/拆分/赎回异常，
    自动跳过该日（不算入 MAE/RMSE 等指标，但会记录在 rows 里 ``skipped=True``）。
    """
    days = [d for d in inputs.trading_days
            if (not start or d >= start) and (not end or d <= end)]
    rows: list[dict] = []
    errs: list[float] = []
    over = 0
    skipped = 0

    for d in days:
        t1 = _prev_trading_day(inputs.trading_days, d)
        if not t1:
            continue
        # 跳变检测：相对 T-1 的涨跌绝对值
        nav_t = inputs.nav_map.get(d)
        nav_t1 = inputs.nav_map.get(t1)
        if nav_t is None or nav_t1 is None or nav_t1 <= 0:
            continue
        nav_jump_pct = abs((nav_t - nav_t1) / nav_t1 * 100.0)
        if nav_jump_pct > skip_jump_threshold_pct:
            rows.append({
                "date": d, "skipped": True, "reason": f"NAV跳变{nav_jump_pct:.2f}%>阈值",
            })
            skipped += 1
            continue
        comp = estimate_for_day(inputs, d, method)
        if comp is None or comp.error_pp is None:
            continue
        e = comp.error_pp
        errs.append(e)
        if abs(e) > THRESHOLD_PP:
            over += 1
        rows.append({
            "date": d,
            "t1_date": comp.estimate.t1_date,
            "t1_nav": comp.estimate.t1_nav,
            "estimated_nav": comp.estimate.estimated_nav,
            "estimated_change_pct": comp.estimate.estimated_change_pct,
            "official_nav": comp.official_nav,
            "official_change_pct": comp.official_change_pct,
            "error_pp": round(e, 4),
            "over_threshold": abs(e) > THRESHOLD_PP,
            "skipped": False,
        })

    if not errs:
        return BacktestResult(
            fund_code=inputs.fund_code, method=method,
            method_label=METHOD_LABELS.get(method, method),
            n=0, mae=0.0, rmse=0.0, max_err=0.0, mean_err=0.0, bias=0.0,
            over_threshold=0, threshold_pp=THRESHOLD_PP, rows=rows,
        )

    mae = sum(abs(e) for e in errs) / len(errs)
    rmse = (sum(e * e for e in errs) / len(errs)) ** 0.5
    mx = max(abs(e) for e in errs)
    mean = sum(errs) / len(errs)
    return BacktestResult(
        fund_code=inputs.fund_code,
        method=method,
        method_label=METHOD_LABELS.get(method, method),
        n=len(errs),
        mae=mae, rmse=rmse, max_err=mx,
        mean_err=mean, bias=mean,
        over_threshold=over,
        threshold_pp=THRESHOLD_PP,
        rows=rows,
        skipped_jump_days=skipped,
    )


def backtest_all_methods(
    fund_code: str,
    start: str = "",
    end: str = "",
    *,
    cache: Optional[CsvCache] = None,
    force: bool = False,
) -> list[BacktestResult]:
    """对全部 5 种方法在同一区间做横向对比。"""
    inputs = load_common_inputs(fund_code, start, end, cache=cache, force=force)
    return [backtest_range(inputs, m, start, end) for m in METHODS]


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="债券型基金回测 CLI",
    )
    parser.add_argument("--fund", required=True, help="6 位债基代码")
    parser.add_argument("--start", default="", help="起始日 YYYY-MM-DD")
    parser.add_argument("--end", default="", help="结束日 YYYY-MM-DD")
    parser.add_argument("--method", default="",
                        help="指定单一方法；留空 = 全部 5 种横向对比")
    parser.add_argument("--force", action="store_true", help="强制重拉数据")
    parser.add_argument("--json", action="store_true", help="输出 JSON")
    args = parser.parse_args(argv)

    inputs = load_common_inputs(args.fund, args.start, args.end, force=args.force)
    methods = [args.method] if args.method else METHODS
    results = [backtest_range(inputs, m, args.start, args.end) for m in methods]

    if args.json:
        print(json.dumps(
            [r.to_dict() for r in results],
            ensure_ascii=False, indent=2,
        ))
        return 0

    print(f"\n=== 债基回测 {args.fund} ({inputs.bond_info.fund_name}) ===")
    print(f"区间: {args.start or '默认'} ~ {args.end or '默认'}")
    print(f"交易日数: {len(inputs.trading_days)}\n")
    print(f"{'方法':<28}{'N':>4}{'MAE':>9}{'RMSE':>9}{'MAX':>9}{'MeanErr':>10}{'Over':>7}")
    print("-" * 78)
    for r in results:
        print(f"{r.method_label:<28}"
              f"{r.n:>4d}"
              f"{r.mae:>9.4f}"
              f"{r.rmse:>9.4f}"
              f"{r.max_err:>9.4f}"
              f"{r.mean_err:>+10.4f}"
              f"{r.over_threshold:>5d}/{r.n}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
