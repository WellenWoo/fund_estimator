"""scripts/gen_dashboard.py — HTML 可视化 dashboard"""
from __future__ import annotations
import sys
import csv
import json
from datetime import date as Date
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core import config


def main():
    """读 results/*.csv 生成 dashboard.html。"""
    rows: list[dict] = []
    for p in config.RESULTS_DIR.glob("daily_batch_*.csv"):
        with p.open("r", encoding="utf-8") as f:
            for r in csv.DictReader(f):
                r["_file"] = p.stem
                r["_method"] = r.get("method", "")
                try:
                    r["err_pp"] = float(r.get("err_pp", 0) or 0)
                    r["est_pct"] = float(r.get("est_pct", 0) or 0)
                    r["off_pct"] = float(r.get("off_pct", 0) or 0)
                except Exception:
                    pass
                rows.append(r)

    # 聚合
    by_method: dict[str, list[dict]] = {}
    for r in rows:
        by_method.setdefault(r["_method"], []).append(r)

    summary = []
    for m, lst in by_method.items():
        errs = [abs(r.get("err_pp", 0) or 0) for r in lst if r.get("err_pp") is not None]
        if not errs:
            continue
        mae = sum(errs) / len(errs)
        over = sum(1 for e in errs if e > 0.5)
        summary.append({"method": m, "N": len(errs), "MAE": mae, "over_th": f"{over}/{len(errs)}"})

    summary.sort(key=lambda x: x["MAE"])
    best = summary[0] if summary else None

    # HTML
    html = ["""<!doctype html>
<html><head><meta charset="utf-8"><title>主动基金 160211 估值 Dashboard</title>
<style>
body { font-family: -apple-system, system-ui, sans-serif; background: #f7f7fb; margin: 0; padding: 24px; }
h1 { color: #1a1a1a; }
.cards { display: flex; gap: 16px; flex-wrap: wrap; }
.card { background: white; border-radius: 8px; padding: 16px 20px; min-width: 220px; box-shadow: 0 1px 3px rgba(0,0,0,0.08); }
.card .label { color: #666; font-size: 12px; text-transform: uppercase; letter-spacing: 0.5px; }
.card .value { font-size: 28px; font-weight: 600; margin-top: 4px; color: #1a1a1a; }
table { background: white; border-collapse: collapse; width: 100%; max-width: 980px; box-shadow: 0 1px 3px rgba(0,0,0,0.08); }
th, td { padding: 10px 14px; text-align: left; border-bottom: 1px solid #eee; }
th { background: #f0f0f5; font-weight: 600; color: #444; }
.badge { background: #22c55e; color: white; padding: 2px 8px; border-radius: 12px; font-size: 12px; }
.timeline { background: white; border-radius: 8px; padding: 16px; box-shadow: 0 1px 3px rgba(0,0,0,0.08); max-width: 980px; margin-top: 24px; }
.row { display: flex; gap: 8px; align-items: center; padding: 4px 0; font-size: 13px; }
.date { width: 100px; color: #666; }
.err-bar { height: 8px; background: #3b82f6; border-radius: 4px; }
.err-num { width: 80px; text-align: right; color: #444; }
</style></head>
<body>
<h1>主动基金估值 Dashboard</h1>
<p>标的: 160211 国泰中小盘成长混合(LOF) | 数据: 东方财富 + 新浪 + 天天基金</p>
<div class="cards">
"""]
    if best:
        html.append(f'<div class="card"><div class="label">当前最佳方法</div><div class="value">{best["method"]}</div></div>')
        html.append(f'<div class="card"><div class="label">MAE</div><div class="value">{best["MAE"]:.4f} pp</div></div>')
        html.append(f'<div class="card"><div class="label">样本数</div><div class="value">{best["N"]}</div></div>')
        html.append(f'<div class="card"><div class="label">超阈值</div><div class="value">{best["over_th"]}</div></div>')

    html.append("""</div>
<h2>多算法对比</h2>
<table>
<tr><th>方法</th><th>N</th><th>MAE (pp)</th><th>超阈值</th></tr>
""")
    for s in summary:
        badge = '<span class="badge">BEST</span>' if s == best else ""
        html.append(f"<tr><td>{s['method']} {badge}</td><td>{s['N']}</td><td>{s['MAE']:.4f}</td><td>{s['over_th']}</td></tr>")
    html.append("</table>")

    # 时间线
    if best and rows:
        method_rows = by_method.get(best["method"], [])
        method_rows.sort(key=lambda r: r.get("date", ""))
        html.append('<div class="timeline"><h2>每日误差 (' + best["method"] + ')</h2>')
        for r in method_rows[-30:]:
            err = abs(r.get("err_pp", 0) or 0)
            width = min(err / 0.5 * 100, 100) * 4  # 0.5pp 对应半格
            html.append(f'<div class="row"><span class="date">{r.get("date", "")}</span>'
                        f'<span class="err-bar" style="width:{width}px"></span>'
                        f'<span class="err-num">{err:.4f}pp</span></div>')
        html.append("</div>")

    html.append("</body></html>")

    out = Path("/workspace/dashboard_active.html")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(html), encoding="utf-8")
    print(f"已生成 → {out}")
    print(f"方法数: {len(summary)}")
    if best:
        print(f"当前最佳: {best['method']}  MAE={best['MAE']:.4f}pp")


if __name__ == "__main__":
    main()
