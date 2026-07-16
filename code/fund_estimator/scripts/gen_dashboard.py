"""生成 HTML dashboard: 显示估值迭代历史 + 当日最新结果。

输入:
- .cache/backtest_*.csv       — 历次回测每日明细
- .cache/daily_batch_*.csv    — 批量生产数据
- .cache/daily_log.csv        — 实时单日生产日志

输出:
- /workspace/dashboard.html    — 单文件、可独立打开看
"""

from __future__ import annotations

import csv
import json
import statistics
from datetime import date, datetime
from pathlib import Path

CACHE = Path(__file__).resolve().parent.parent / ".cache"
OUT = Path("/workspace/dashboard.html")


def load_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


def num(s: str) -> float | None:
    try:
        return float(s)
    except (ValueError, TypeError):
        return None


def summarize(rs: list[dict], err_key: str = "abs_error_pp") -> dict:
    abs_errs: list[float] = []
    signed: list[float] = []
    for r in rs:
        if err_key in r:
            v = num(r[err_key])
            if v is not None:
                abs_errs.append(abs(v))
        if "rel_error_pp" in r:
            v = num(r["rel_error_pp"])
            if v is not None:
                signed.append(v)
    if not abs_errs:
        return {}
    return {
        "n": len(abs_errs),
        "mae": round(statistics.mean(abs_errs), 4),
        "rmse": round(statistics.sqrt(statistics.fmean(e * e for e in signed)), 4),
        "mean_err": round(statistics.mean(signed), 4),
        "max_err": round(max(abs_errs), 4),
        "median_err": round(statistics.median(abs_errs), 4),
    }


def collect_backtests() -> list[dict]:
    """收集所有 backtest_*.csv, 按方法名聚合."""
    methods: dict[str, dict] = {}
    for p in CACHE.glob("backtest_*.csv"):
        name = p.stem  # backtest_<fund>_<method>_<start>_<end>
        parts = name.split("_")
        if len(parts) < 6:
            continue
        fund = parts[1]
        method = "_".join(parts[2:-2])
        start = parts[-2]
        end = parts[-1]
        rs = load_csv(p)
        for r in rs:
            r["_mae"] = num(r.get("abs_error_pp"))
            r["_signed"] = num(r.get("rel_error_pp"))
        s = summarize(rs)
        if not s:
            continue
        methods.setdefault(method, {"method": method, "runs": []})
        methods[method]["runs"].append(
            {"fund": fund, "start": start, "end": end, "summary": s, "rows": rs}
        )
    return list(methods.values())


def make_method_label(m: str) -> str:
    table = {
        "v_top10": "持仓还原 top10",
        "v_residual": "top10 + 现金拖累",
        "v_residual_uncovered": "top10 + uncovered 代理",
        "v_index_full": "创业板指 + 现金拖累",
        "v_index_full_no_cash": "创业板指（无拖累）⭐",
        "v_index_blend": "top10 + 创业板指混合",
    }
    return table.get(m, m)


def best_method(backtests: list[dict]) -> tuple[str, dict] | None:
    best_m, best_s, best_n = None, None, 0
    for mt in backtests:
        for r in mt["runs"]:
            if not r["summary"]:
                continue
            n = r["summary"]["n"]
            if n < best_n:
                continue
            mae = r["summary"]["mae"]
            if best_s is None or mae < best_s["mae"] or (mae == best_s["mae"] and n > best_n):
                best_m, best_s = mt["method"], r["summary"]
                best_n = n
    if best_m is None:
        return None
    return best_m, best_s


def render_html(backtests: list[dict], batch_runs: list[dict], latest: dict | None) -> str:
    best = best_method(backtests)
    rows_html = ""
    for mt in backtests:
        label = make_method_label(mt["method"])
        for r in mt["runs"]:
            s = r["summary"]
            tag = ""
            if best and mt["method"] == best[0]:
                tag = " 🏆"
            rows_html += f"""
            <tr>
              <td>{label}{tag}</td>
              <td>{r['start']}</td>
              <td>{r['end']}</td>
              <td>{s['n']}</td>
              <td><b>{s['mae']:.4f}</b></td>
              <td>{s['rmse']:.4f}</td>
              <td>{s['mean_err']:+.4f}</td>
              <td>{s['max_err']:.4f}</td>
            </tr>
            """

    # 每日散点
    scatter_data: list[tuple[str, float, float]] = []
    for mt in backtests:
        for r in mt["runs"]:
            for row in r["rows"]:
                d = row.get("date")
                e = num(row.get("rel_error_pp") or row.get("abs_error_pp"))
                if d and e is not None:
                    scatter_data.append((d, e, row.get("actual_pct") or row.get("actual_change_pct") or 0))
    scatter_data.sort(key=lambda x: x[0])
    scatter_json = json.dumps(scatter_data)

    latest_html = ""
    if latest:
        latest_html = f"""
        <div class="latest">
          <h2>最新一天的结果（{latest.get('trade_date', '?')}）</h2>
          <table>
            <tr><th>方法</th><td>{latest.get('method', '?')}</td></tr>
            <tr><th>T-1 NAV</th><td>{latest.get('t1_nav', '?')}</td></tr>
            <tr><th>估算 NAV</th><td>{latest.get('estimated_nav', '?')}</td></tr>
            <tr><th>官方 NAV</th><td>{latest.get('official_nav', '?')}</td></tr>
            <tr><th>绝对误差 (pp)</th><td>{latest.get('abs_error_ppct', '?')}</td></tr>
            <tr><th>相对误差 (pp)</th><td>{latest.get('rel_error_ppct', '?')}</td></tr>
          </table>
        </div>
        """

    # 时间线
    timeline = []
    for mt in backtests:
        for r in mt["runs"]:
            if not r["summary"]:
                continue
            timeline.append(
                {
                    "method": mt["method"],
                    "label": make_method_label(mt["method"]),
                    "start": r["start"],
                    "end": r["end"],
                    "mae": r["summary"]["mae"],
                    "n": r["summary"]["n"],
                    "mean_err": r["summary"]["mean_err"],
                }
            )
    timeline.sort(key=lambda x: x["start"])
    timeline_html = "<ul>"
    for t in timeline:
        timeline_html += f"<li><b>{t['label']}</b> ({t['start']} → {t['end']}, N={t['n']}): MAE={t['mae']:.4f} pp, bias={t['mean_err']:+.4f}</li>"
    timeline_html += "</ul>"

    css = """
    body { font-family: -apple-system, system-ui, sans-serif; margin: 20px; color: #222; }
    h1 { color: #c00; border-bottom: 3px solid #c00; padding-bottom: 8px; }
    h2 { color: #036; margin-top: 24px; }
    table { border-collapse: collapse; margin: 12px 0; }
    th, td { border: 1px solid #ccc; padding: 6px 12px; text-align: right; }
    th { background: #f5f5f5; }
    td:first-child, th:first-child { text-align: left; }
    tr:nth-child(even) { background: #fafafa; }
    .latest { background: #fffacd; padding: 12px; border-radius: 8px; margin: 12px 0; }
    canvas { max-width: 100%; }
    .meta { color: #888; font-size: 12px; margin-bottom: 20px; }
    """
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>基金估值迭代 Dashboard</title>
<style>{css}</style></head>
<body>
<h1>LOF 160223 实时估值算法 — 迭代 Dashboard</h1>
<p class="meta">生成时间: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")} · 数据源: code/fund_estimator/.cache/</p>

<h2>1. 当前最佳方法</h2>
{f"<p>🏆 <b>{make_method_label(best[0])}</b> — MAE=<b>{best[1]['mae']:.4f}</b> pp (N={best[1]['n']})</p>" if best else "<p>暂无数据</p>"}
{latest_html}

<h2>2. 各方法对比（46 天样本）</h2>
<table>
<thead><tr><th>方法</th><th>开始</th><th>结束</th><th>N</th><th>MAE_pp</th><th>RMSE_pp</th><th>Mean pp</th><th>Max pp</th></tr></thead>
<tbody>{rows_html}</tbody>
</table>

<h2>3. 每日误差时间线</h2>
<canvas id="scatter" height="280"></canvas>
<script>
const pts = {scatter_json};
const ctx = document.getElementById('scatter').getContext('2d');
ctx.fillStyle = '#333';
ctx.fillText('每日误差 (单位: pp)', 10, 20);
ctx.fillText('+0.5 (阈值)', 600, 30);
ctx.fillText('-0.5', 600, 270);
const w = ctx.canvas.width, h = ctx.canvas.height;
ctx.strokeStyle = '#fbb';
ctx.beginPath();
ctx.moveTo(0, 30); ctx.lineTo(w, 30);
ctx.moveTo(0, 270); ctx.lineTo(w, 270);
ctx.stroke();
ctx.fillStyle = '#06c';
for (const p of pts) {{
  const x = 30 + (Date.parse(p[0]) - Date.parse('{scatter_data[0][0] if scatter_data else "2026-01-01"}')) / (86400000 * 60) * w;
  const y = h/2 - p[1] * 100;
  ctx.beginPath();
  ctx.arc(x, y, 2, 0, Math.PI*2);
  ctx.fill();
}}
</script>

<h2>4. 历次迭代时间线</h2>
{timeline_html}

<h2>5. 操作入口</h2>
<pre>
# 跑新一轮对比
python3 code/fund_estimator/backtest/iteration_tracker.py \\
  --start 2026-04-25 --end 2026-07-06

# 单日盘后估值
python3 code/fund_estimator/scripts/daily_close_estimate.py \\
  --method v_index_full_no_cash \\
  --trade-date 2026-07-06 \\
  --fetch-official
</pre>
</body></html>
"""


def main():
    backtests = collect_backtests()
    batch_runs = list(CACHE.glob("daily_batch_*.csv"))
    daily_log = load_csv(CACHE / "daily_log.csv")

    latest = None
    if daily_log:
        # 找 latest 一行
        for r in reversed(daily_log):
            if r.get("estimated_nav") and r.get("official_nav"):
                latest = r
                break

    html = render_html(backtests, batch_runs, latest)
    OUT.write_text(html, encoding="utf-8")
    print(f"已生成 → {OUT}")
    print(f"方法数: {len(backtests)}")
    if backtests:
        b = best_method(backtests)
        if b:
            print(f"当前最佳: {b[0]}  MAE={b[1]['mae']:.4f}pp")


if __name__ == "__main__":
    main()
