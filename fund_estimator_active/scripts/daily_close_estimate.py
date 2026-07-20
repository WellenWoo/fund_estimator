"""scripts/daily_close_estimate.py — 单日盘后生产脚本

跑 1 天, 6 种算法, 选最佳, 对比官方 NAV。
"""
from __future__ import annotations
import sys
import json
import argparse
from datetime import date as Date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from data_sources.eastmoney.nav_history import fetch_history
from data_sources.eastmoney.holding import fetch_top10, fetch_fund_meta
from data_sources.benchmark.get_benchmark import benchmark_return, list_benchmarks
from data_sources.sina.history import fetch_kline, get_return_pct
from data_sources.tiantian.gz_realtime import fetch_tiantian_gz
from data_sources import cache
from core import config
from backtest.run_backtest import _to_fund_holding_from_top10, _load_quotes_from_klines
from estimators.holdings_based import estimate_v_active_top10
from estimators.benchmark_proxy import estimate_v_active_bench
from estimators.alpha_residual import estimate_v_active_alpha
from estimators.blend import estimate_v_active_top10_blend, estimate_v_active_top10_resid


def fetch_official_nav(fund_code: str, target_date: Date) -> float | None:
    """从天天基金 fundgz 接口拿最新官方 NAV (含 jzrq)。"""
    # 该接口返回昨日 (T-1) 收盘 NAV, 需要 T 日 21:00 后才更新
    data = fetch_tiantian_gz(fund_code)
    if data and data.get("dwjz"):
        try:
            return float(data["dwjz"])
        except Exception:
            return None
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--method", default="v_active_top10_blend",
                    help="v_active_top10 / v_active_bench_csi1000 / v_active_top10_blend ...")
    ap.add_argument("--alpha", type=float, default=0.5)
    ap.add_argument("--bench", default="csi1000")
    ap.add_argument("--trade-date", default=None, help="YYYY-MM-DD, 默认今天")
    ap.add_argument("--fetch-official", action="store_true",
                    help="从天天基金拉取官方 NAV 做对比")
    args = ap.parse_args()

    today = Date.fromisoformat(args.trade_date) if args.trade_date else Date.today()
    fund_code = config.FUND_CODE

    print(f"=== 主动基金 {fund_code} 盘后估值 ===")
    print(f"  today: {today}, method: {args.method}, bench: {args.bench}, alpha: {args.alpha}")

    # 拉 NAV 历史
    nav_history = fetch_history(fund_code, start=Date(2026, 1, 1), end=today, force=False)
    if not nav_history:
        print("ERR: 拉不到 NAV 历史")
        return

    # 找 T-1
    sorted_nav = sorted([r for r in nav_history if r.get("date") and r["date"] < today],
                        key=lambda r: r["date"])
    if not sorted_nav:
        print("ERR: 找不到 T-1 NAV")
        return
    t1_row = sorted_nav[-1]
    t1_date, t1_nav = t1_row["date"], t1_row["nav"]

    # 持仓
    top10 = fetch_top10(fund_code)
    meta = fetch_fund_meta(fund_code)
    fund_name = meta.get("name", config.FUND_NAME)
    stock_pos = meta.get("stock_position_pct", 95.0)
    holding = _to_fund_holding_from_top10(top10, fund_code, fund_name, stock_pos)

    # 股票行情 (从缓存 kline 取历史 close 算区间涨跌幅)
    codes = [p.code for p in top10]
    quotes = _load_quotes_from_klines(codes, t1_date, today)

    # benchmark
    bench_ret = benchmark_return(args.bench, t1_date, today) or 0.0

    # 选定算法
    if args.method == "v_active_top10":
        est = estimate_v_active_top10(holding, t1_nav, today, quotes)
    elif args.method.startswith("v_active_bench_"):
        key = args.method.replace("v_active_bench_", "")
        est = estimate_v_active_bench(t1_nav, today, t1_date, bench_ret, key,
                                       fund_code=fund_code, fund_name=fund_name)
    elif args.method == "v_active_top10_blend":
        est = estimate_v_active_top10_blend(holding, t1_nav, today, t1_date,
                                            quotes, bench_ret, args.bench, alpha=args.alpha)
    elif args.method == "v_active_alpha":
        est = estimate_v_active_alpha(holding, t1_nav, today, t1_date,
                                      quotes, bench_ret, args.bench)
    elif args.method.startswith("v_active_top10_resid_"):
        key = args.method.replace("v_active_top10_resid_", "")
        est = estimate_v_active_top10_resid(holding, t1_nav, today, t1_date,
                                            quotes, bench_ret, key)
    else:
        print(f"ERR: 未知方法 {args.method}")
        return

    if not est:
        print("ERR: 估算失败")
        return

    # 拉官方 NAV 对比
    if args.fetch_official:
        off = fetch_official_nav(fund_code, today)
        if off:
            est.official_nav = off
            est.official_change_pct = (off - t1_nav) / t1_nav
            err = est.error_pp()
            print(f"\n对比官方 NAV {off}: 差异 {est.estimated_nav - off:+.4f} "
                  f"({err:+.4f}%)" if err else "")
        else:
            print("  (官方 NAV 尚未披露)")

    # 输出
    out = est.to_dict()
    out["t1_date"] = t1_date.isoformat()
    out["t1_nav"] = t1_nav
    print("\n" + json.dumps(out, ensure_ascii=False, indent=2))

    # 落盘到 daily_log
    log_row = {
        "date": today.isoformat(),
        "method": est.method,
        "est_nav": est.estimated_nav,
        "off_nav": est.official_nav or "",
        "err_pp": est.error_pp() if est.error_pp() is not None else "",
        "est_pct": est.estimated_change_pct,
        "off_pct": est.official_change_pct or "",
    }
    cache.append_row("daily_log_160211", log_row)


if __name__ == "__main__":
    main()
