"""HTML 可视化 dashboard —— scripts/gen_dashboard.py。

README §3.4：读取 .cache/ 里 iteration_tracker 落盘的对比结果与每日误差，
生成一份自包含的 HTML dashboard（无第三方 JS 依赖，纯 canvas 画散点）。

输出：<repo_root>/dashboard.html （与现有 dashboard.html 同位置）。

数据来源优先级：
1. .cache/iteration_results.csv + .cache/daily_errors.csv（iteration_tracker 生成）
2. 若不存在，则现场跑一次 iteration_tracker.run_all() 生成。
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import os
import sys
from typing import Optional

_THIS = os.path.dirname(os.path.abspath(__file__))
_CODE_ROOT = os.path.dirname(os.path.dirname(_THIS))      # code/
_REPO_ROOT = os.path.dirname(_CODE_ROOT)                  # value/
if _CODE_ROOT not in sys.path:
    sys.path.insert(0, _CODE_ROOT)

from fund_estimator.data_sources.cache import cache_dir  # noqa: E402
from fund_estimator.backtest.iteration_tracker import (  # noqa: E402
    run_all,
    save_results,
    pick_best,
    ITER_RESULTS_CSV,
    DAILY_ERRORS_CSV,
)
from fund_estimator.estimators.holdings_based import DEFAULT_METHOD  # noqa: E402


def _read_csv(path: str) -> list[dict]:
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8", newline="") as fh:
        return list(csv.DictReader(fh))


def _load_or_build(force_rebuild: bool, start: str, end: str) -> tuple[list[dict], list[dict]]:
    cdir = cache_dir()
    stats_path = os.path.join(cdir, ITER_RESULTS_CSV)
    daily_path = os.path.join(cdir, DAILY_ERRORS_CSV)
    if not force_rebuild and os.path.exists(stats_path) and os.path.exists(daily_path):
        return _read_csv(stats_path), _read_csv(daily_path)
    # 现场生成
    stats_rows, daily_rows = run_all(start=start, end=end)
    save_results(stats_rows, daily_rows)
    return _read_csv(stats_path), _read_csv(daily_path)


def _f(v, default=0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def build_html(stats_rows: list[dict], daily_rows: list[dict]) -> str:
    now = dt.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    best = pick_best([
        {**s, "mae_pp": _f(s.get("mae_pp")), "over_threshold": int(_f(s.get("over_threshold"))),
         "n": int(_f(s.get("n")))}
        for s in stats_rows
    ]) if stats_rows else None

    # 主推方法的每日序列
    main_method = best["method"] if best else DEFAULT_METHOD
    main_daily = [r for r in daily_rows if r.get("method") == main_method]
    main_daily.sort(key=lambda r: r.get("date", ""))

    # 最新一天
    latest = main_daily[-1] if main_daily else None

    # 各方法对比表
    rows_html = ""
    for s in sorted(stats_rows, key=lambda x: _f(x.get("mae_pp"), 1e9)):
        if int(_f(s.get("n"))) == 0:
            continue
        star = " 🏆" if best and s.get("method") == best["method"] else ""
        rows_html += f"""
            <tr>
              <td>{s.get('label', s.get('method'))}{star}</td>
              <td>{s.get('start','')}</td>
              <td>{s.get('end','')}</td>
              <td>{int(_f(s.get('n')))}</td>
              <td><b>{_f(s.get('mae_pp')):.4f}</b></td>
              <td>{_f(s.get('rmse_pp')):.4f}</td>
              <td>{_f(s.get('mean_pp')):+.4f}</td>
              <td>{_f(s.get('max_pp')):.4f}</td>
              <td>{s.get('over_ratio','')}</td>
            </tr>"""

    # 最新一天卡片
    latest_html = ""
    if latest:
        err_pp = _f(latest.get("error_pp"))
        latest_html = f"""
        <div class="latest">
          <h2>最新一天的结果（{latest.get('date','')}）</h2>
          <table>
            <tr><th>方法</th><td>{latest.get('method','')}</td></tr>
            <tr><th>T-1 NAV</th><td>{latest.get('t1_nav','')}</td></tr>
            <tr><th>估算 NAV</th><td>{latest.get('estimated_nav','')}</td></tr>
            <tr><th>官方 NAV</th><td>{latest.get('official_nav','')}</td></tr>
            <tr><th>绝对误差 (pp)</th><td>{err_pp:+.4f}</td></tr>
            <tr><th>是否超阈值(0.5pp)</th><td>{'是 ⚠️' if abs(err_pp) > 0.5 else '否 ✅'}</td></tr>
          </table>
        </div>"""

    # 散点数据（主推方法每日误差）
    pts = [[r.get("date", ""), round(_f(r.get("error_pp")), 4),
            r.get("official_change_pct", "")] for r in main_daily]
    pts_json = json.dumps(pts, ensure_ascii=False)

    # 迭代时间线
    timeline_html = ""
    for s in stats_rows:
        if int(_f(s.get("n"))) == 0:
            continue
        timeline_html += (
            f"<li><b>{s.get('label', s.get('method'))}</b> "
            f"({s.get('start','')} ~ {s.get('end','')}, N={int(_f(s.get('n')))}): "
            f"MAE={_f(s.get('mae_pp')):.4f} pp, bias={_f(s.get('mean_pp')):+.4f}</li>"
        )

    best_line = ""
    if best:
        best_line = (f"🏆 <b>{best.get('label', best['method'])}</b>："
                     f"MAE=<b>{_f(best.get('mae_pp')):.4f}</b> pp (N={int(_f(best.get('n')))}, "
                     f"超阈值 {best.get('over_ratio','')})")

    start_date = pts[0][0] if pts else ""
    span_days = 70

    html = f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8"><title>基金估值迭代 Dashboard</title>
<style>
    body {{ font-family: -apple-system, system-ui, "Microsoft YaHei", sans-serif; margin: 20px; color: #222; }}
    h1 {{ color: #c00; border-bottom: 3px solid #c00; padding-bottom: 8px; }}
    h2 {{ color: #036; margin-top: 24px; }}
    table {{ border-collapse: collapse; margin: 12px 0; }}
    th, td {{ border: 1px solid #ccc; padding: 6px 12px; text-align: right; }}
    th {{ background: #f5f5f5; }}
    td:first-child, th:first-child {{ text-align: left; }}
    tr:nth-child(even) {{ background: #fafafa; }}
    .latest {{ background: #fffacd; padding: 12px; border-radius: 8px; margin: 12px 0; }}
    canvas {{ max-width: 100%; border: 1px solid #eee; }}
    .meta {{ color: #888; font-size: 12px; margin-bottom: 20px; }}
    pre {{ background: #f7f7f7; padding: 12px; border-radius: 6px; overflow-x: auto; }}
</style></head>
<body>
<h1>LOF 160223 实时估值算法 · 迭代 Dashboard</h1>
<p class="meta">生成时间: {now} · 数据源: code/fund_estimator/.cache/</p>

<h2>1. 当前最佳方案</h2>
<p>{best_line}</p>
{latest_html}

<h2>2. 各方法对比</h2>
<table>
<thead><tr><th>方法</th><th>开始</th><th>结束</th><th>N</th><th>MAE_pp</th><th>RMSE_pp</th><th>Mean pp</th><th>Max pp</th><th>超阈值</th></tr></thead>
<tbody>{rows_html}
</tbody>
</table>

<h2>3. 每日误差时间序列（主推 {main_method}）</h2>
<canvas id="scatter" width="900" height="300"></canvas>
<script>
const pts = {pts_json};
const startDate = "{start_date}";
const spanDays = {span_days};
const ctx = document.getElementById('scatter').getContext('2d');
const w = ctx.canvas.width, h = ctx.canvas.height;
ctx.clearRect(0,0,w,h);
ctx.fillStyle = '#333';
ctx.fillText('每日误差 (单位: pp)', 10, 16);
// 阈值线 +/-0.5pp
ctx.strokeStyle = '#fbb';
const yFor = (v) => h/2 - v * 200;   // 1pp = 200px
ctx.beginPath();
ctx.moveTo(0, yFor(0.5)); ctx.lineTo(w, yFor(0.5));
ctx.moveTo(0, yFor(-0.5)); ctx.lineTo(w, yFor(-0.5));
ctx.stroke();
ctx.fillStyle = '#c00';
ctx.fillText('+0.5 阈值', w-70, yFor(0.5)-4);
ctx.fillText('-0.5 阈值', w-70, yFor(-0.5)+14);
// 零线
ctx.strokeStyle = '#ddd';
ctx.beginPath(); ctx.moveTo(0, h/2); ctx.lineTo(w, h/2); ctx.stroke();
// 散点
const base = startDate ? Date.parse(startDate) : Date.now();
for (const p of pts) {{
  const d = Date.parse(p[0]);
  const x = 40 + (d - base) / (86400000 * spanDays) * (w - 60);
  const y = yFor(p[1]);
  ctx.fillStyle = Math.abs(p[1]) > 0.5 ? '#e00' : '#06c';
  ctx.beginPath();
  ctx.arc(x, Math.max(4, Math.min(h-4, y)), 3, 0, Math.PI*2);
  ctx.fill();
}}
</script>

<h2>4. 历次迭代对比</h2>
<ul>{timeline_html}</ul>

<h2>5. 操作入口</h2>
<pre>
# 跑新一轮 5 方法对比
python code/fund_estimator/backtest/iteration_tracker.py --start 2026-04-25 --end 2026-07-14

# 单日盘后估值
python code/fund_estimator/scripts/daily_close_estimate.py \\
  --method v_index_full_no_cash --trade-date 2026-07-14 --fetch-official

# 重新生成本页
python code/fund_estimator/scripts/gen_dashboard.py
</pre>
</body></html>"""
    return html


def main(argv: Optional[list[str]] = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
    parser = argparse.ArgumentParser(description="生成 HTML dashboard")
    parser.add_argument("--out", default=os.path.join(_REPO_ROOT, "dashboard.html"))
    parser.add_argument("--start", default="2026-04-25")
    parser.add_argument("--end", default="2026-07-14")
    parser.add_argument("--rebuild", action="store_true", help="忽略缓存，现场重跑对比")
    args = parser.parse_args(argv)

    stats_rows, daily_rows = _load_or_build(args.rebuild, args.start, args.end)
    html = build_html(stats_rows, daily_rows)
    with open(args.out, "w", encoding="utf-8") as fh:
        fh.write(html)
    print(f"dashboard 已生成: {args.out}")
    print(f"  方法数: {len(stats_rows)}  每日记录: {len(daily_rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
