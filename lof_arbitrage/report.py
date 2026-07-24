"""
报告生成模块
============

生成文本格式、HTML格式的套利分析报告。
"""

import json
from datetime import datetime
from typing import Dict, List


def generate_text_report(analysis_result: Dict) -> str:
    """
    生成纯文本报告

    Args:
        analysis_result: run_analysis 返回的结果字典

    Returns:
        文本报告字符串
    """
    lines = []
    lines.append("=" * 70)
    lines.append("LOF基金折价/溢价套利分析报告")
    lines.append("=" * 70)
    lines.append(f"生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append("")

    summary = analysis_result.get("summary", {})
    results = analysis_result.get("results", {})

    # 汇总信息
    lines.append("【分析汇总】")
    lines.append(f"  基金总数：{summary.get('total', 0)} 只")
    lines.append(f"  成功分析：{summary.get('success', 0)} 只")
    lines.append(f"  失败：{len(summary.get('errors', []))} 只")
    lines.append(f"  套利机会：{summary.get('arbitrage_opportunities', 0)} 个")

    buy_list = summary.get("buy_arbitrage_signals", [])
    sell_list = summary.get("sell_arbitrage_signals", [])
    if buy_list:
        lines.append(f"  折价套利机会：{', '.join(buy_list)}")
    if sell_list:
        lines.append(f"  溢价套利机会：{', '.join(sell_list)}")
    lines.append("")

    # 各基金详情
    lines.append("-" * 70)
    lines.append("【各基金详情】")
    lines.append("-" * 70)

    for code, result in results.items():
        lines.append("")
        lines.append(f"  ▶ {code}")
        lines.append("  " + "=" * 50)

        if "error" in result:
            lines.append(f"  错误：{result['error']}")
            continue

        fund_info = result.get("fund_info", {})
        nav_est = result.get("nav_estimate", {})
        signal = result.get("signal", {})

        # 基金基本信息
        lines.append(f"  基金名称：{fund_info.get('name', '未知')}")
        lines.append(f"  基金类型：{fund_info.get('fund_type', '未知')}")
        lines.append(f"  基金规模：{fund_info.get('size', 0):.2f} 亿元")
        lines.append(f"  基金经理：{fund_info.get('manager', '未知')}")

        # 净值信息
        lines.append("")
        lines.append(f"  最新净值：{fund_info.get('last_nav', 0):.4f}（{fund_info.get('last_nav_date', '未知')}）")
        lines.append(f"  净值涨跌幅：{fund_info.get('last_nav_change', 0):+.2f}%")

        # 估值信息
        if nav_est:
            lines.append("")
            lines.append(f"  估算净值：{nav_est.get('estimated_nav', 0):.4f}")
            lines.append(f"  估算涨跌幅：{nav_est.get('estimated_change', 0):+.2f}%")
            lines.append(f"  估值算法：{nav_est.get('algorithm', '未知')}")
            lines.append(f"  置信度：{nav_est.get('confidence', 0):.0%}")

        # 场内行情
        lines.append("")
        lines.append(f"  场内价格：{signal.get('market_price', 0):.4f}")
        lines.append(f"  场内涨跌幅：{fund_info.get('market_change', 0):+.2f}%")
        lines.append(f"  成交额：{fund_info.get('market_amount', 0):.2f} 万元")

        # 折溢价
        lines.append("")
        premium = signal.get('premium_rate', 0)
        direction = "溢价" if premium > 0 else ("折价" if premium < 0 else "平价")
        lines.append(f"  折溢价率：{premium:+.3f}%（{direction}）")
        lines.append(f"  套利总成本：{signal.get('total_cost', 0):.3f}%")
        lines.append(f"  预期利润率：{signal.get('profit_margin', 0):+.3f}%")

        # 信号
        lines.append("")
        signal_type = signal.get("signal", "neutral")
        signal_strength = signal.get("signal_strength", 0)
        trigger = signal.get("trigger_level", "无")

        if signal_type == "buy_arbitrage":
            signal_text = f"🔴 折价套利信号（强度 {signal_strength:.0%}，触发等级：{trigger}）"
        elif signal_type == "sell_arbitrage":
            signal_text = f"🟢 溢价套利信号（强度 {signal_strength:.0%}，触发等级：{trigger}）"
        else:
            signal_text = f"⚪ 无套利信号"
        lines.append(f"  信号：{signal_text}")

        # 风险
        lines.append("")
        lines.append(f"  流动性风险：{signal.get('liquidity_risk', '未知')}")
        lines.append(f"  估值误差风险：{signal.get('estimation_risk', '未知')}")
        lines.append(f"  时间差风险：{signal.get('time_risk', '未知')}")

        # 建议
        lines.append("")
        lines.append(f"  建议：{signal.get('suggestion', '')}")

    lines.append("")
    lines.append("=" * 70)
    lines.append("【风险提示】")
    lines.append("  1. 本报告仅供参考，不构成任何投资建议。")
    lines.append("  2. LOF套利存在时间差风险、流动性风险、估值偏差风险等。")
    lines.append("  3. 套利需T+2完成，期间净值可能大幅波动。")
    lines.append("  4. 请充分了解交易规则和风险后审慎决策。")
    lines.append("=" * 70)

    return "\n".join(lines)


def generate_json_report(analysis_result: Dict, indent: int = 2) -> str:
    """生成JSON格式报告"""
    return json.dumps(analysis_result, ensure_ascii=False, indent=indent)


def generate_simple_html_report(analysis_result: Dict) -> str:
    """
    生成简单的HTML报告（轻量级，无外部依赖）

    对于完整的可视化HTML报告，建议使用 html-report skill 单独生成。
    """
    summary = analysis_result.get("summary", {})
    results = analysis_result.get("results", {})

    html_parts = []
    html_parts.append("<!DOCTYPE html>")
    html_parts.append('<html lang="zh-CN"><head><meta charset="UTF-8">')
    html_parts.append("<title>LOF基金套利分析报告</title>")
    html_parts.append("<style>")
    html_parts.append("body{font-family:'Microsoft YaHei',sans-serif;margin:20px;background:#f5f5f5;}")
    html_parts.append(".container{max-width:900px;margin:0 auto;background:#fff;padding:20px;border-radius:8px;box-shadow:0 2px 8px rgba(0,0,0,0.1);}")
    html_parts.append("h1{color:#1a1d2e;border-bottom:2px solid #2563eb;padding-bottom:10px;}")
    html_parts.append("h2{color:#2563eb;margin-top:25px;}")
    html_parts.append(".summary{background:#eff6ff;padding:15px;border-radius:6px;margin:15px 0;}")
    html_parts.append(".fund-card{border:1px solid #e5e7eb;border-radius:8px;padding:15px;margin:15px 0;}")
    html_parts.append(".fund-card h3{margin-top:0;color:#1a1d2e;}")
    html_parts.append(".metric{display:inline-block;margin:5px 15px 5px 0;}")
    html_parts.append(".metric .label{color:#6b7280;font-size:0.85em;}")
    html_parts.append(".metric .value{font-size:1.2em;font-weight:bold;}")
    html_parts.append(".positive{color:#16a34a;}")
    html_parts.append(".negative{color:#dc2626;}")
    html_parts.append(".neutral{color:#2563eb;}")
    html_parts.append(".signal-buy{background:#dcfce7;color:#166534;padding:5px 10px;border-radius:20px;font-weight:bold;display:inline-block;}")
    html_parts.append(".signal-sell{background:#fee2e2;color:#991b1b;padding:5px 10px;border-radius:20px;font-weight:bold;display:inline-block;}")
    html_parts.append(".signal-neutral{background:#f3f4f6;color:#374151;padding:5px 10px;border-radius:20px;font-weight:bold;display:inline-block;}")
    html_parts.append("table{width:100%;border-collapse:collapse;margin:10px 0;}")
    html_parts.append("th,td{padding:8px 12px;text-align:left;border-bottom:1px solid #e5e7eb;}")
    html_parts.append("th{background:#f8fafc;font-weight:600;}")
    html_parts.append(".risk-low{color:#16a34a;}")
    html_parts.append(".risk-mid{color:#ea580c;}")
    html_parts.append(".risk-high{color:#dc2626;}")
    html_parts.append(".suggestion{background:#fff7ed;border-left:4px solid #ea580c;padding:10px 15px;margin:10px 0;border-radius:0 6px 6px 0;}")
    html_parts.append(".footer{margin-top:30px;padding-top:15px;border-top:1px solid #e5e7eb;font-size:0.85em;color:#6b7280;}")
    html_parts.append("</style></head><body><div class='container'>")

    html_parts.append("<h1>LOF基金折价/溢价套利分析报告</h1>")
    html_parts.append(f"<p>生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>")

    # 汇总
    html_parts.append("<div class='summary'>")
    html_parts.append("<h2>分析汇总</h2>")
    html_parts.append(f"<p>基金总数：<b>{summary.get('total', 0)}</b> 只 | "
                      f"成功：<b>{summary.get('success', 0)}</b> 只 | "
                      f"套利机会：<b class='positive'>{summary.get('arbitrage_opportunities', 0)}</b> 个</p>")

    buy = summary.get("buy_arbitrage_signals", [])
    sell = summary.get("sell_arbitrage_signals", [])
    if buy:
        html_parts.append(f"<p>折价套利机会：<span class='signal-buy'>{', '.join(buy)}</span></p>")
    if sell:
        html_parts.append(f"<p>溢价套利机会：<span class='signal-sell'>{', '.join(sell)}</span></p>")
    html_parts.append("</div>")

    # 各基金详情
    html_parts.append("<h2>各基金详情</h2>")

    for code, result in results.items():
        html_parts.append(f"<div class='fund-card'>")
        html_parts.append(f"<h3>{code}</h3>")

        if "error" in result:
            html_parts.append(f"<p style='color:#dc2626;'>错误：{result['error']}</p>")
            html_parts.append("</div>")
            continue

        fund = result.get("fund_info", {})
        nav_est = result.get("nav_estimate", {})
        signal = result.get("signal", {})

        # 基本信息
        html_parts.append(f"<p><b>{fund.get('name', '未知')}</b> | "
                          f"{fund.get('fund_type', '未知')} | "
                          f"规模：{fund.get('size', 0):.2f}亿元 | "
                          f"经理：{fund.get('manager', '未知')}</p>")

        # 核心指标
        premium = signal.get('premium_rate', 0)
        premium_class = "positive" if premium > 0 else ("negative" if premium < 0 else "neutral")
        signal_type = signal.get("signal", "neutral")

        html_parts.append("<div>")
        html_parts.append(f"<div class='metric'><div class='label'>净值</div>"
                          f"<div class='value neutral'>{fund.get('last_nav', 0):.4f}</div></div>")
        html_parts.append(f"<div class='metric'><div class='label'>估算净值</div>"
                          f"<div class='value neutral'>{nav_est.get('estimated_nav', 0):.4f}</div></div>")
        html_parts.append(f"<div class='metric'><div class='label'>场内价格</div>"
                          f"<div class='value neutral'>{signal.get('market_price', 0):.4f}</div></div>")
        html_parts.append(f"<div class='metric'><div class='label'>折溢价率</div>"
                          f"<div class='value {premium_class}'>{premium:+.3f}%</div></div>")
        html_parts.append(f"<div class='metric'><div class='label'>套利成本</div>"
                          f"<div class='value'>{signal.get('total_cost', 0):.3f}%</div></div>")
        html_parts.append("</div>")

        # 信号
        html_parts.append("<p>")
        if signal_type == "buy_arbitrage":
            html_parts.append(f"<span class='signal-buy'>🔴 折价套利信号（强度 {signal.get('signal_strength', 0):.0%}）</span>")
        elif signal_type == "sell_arbitrage":
            html_parts.append(f"<span class='signal-sell'>🟢 溢价套利信号（强度 {signal.get('signal_strength', 0):.0%}）</span>")
        else:
            html_parts.append(f"<span class='signal-neutral'>⚪ 无套利信号</span>")
        html_parts.append("</p>")

        # 风险评估
        html_parts.append("<table>")
        html_parts.append("<tr><th>风险类型</th><th>等级</th><th>说明</th></tr>")
        liq = signal.get('liquidity_risk', '未知')
        est = signal.get('estimation_risk', '未知')
        tm = signal.get('time_risk', '未知')

        def risk_class(r):
            if r in ('低',):
                return 'risk-low'
            elif r in ('中', '中高'):
                return 'risk-mid'
            else:
                return 'risk-high'

        html_parts.append(f"<tr><td>流动性风险</td><td class='{risk_class(liq)}'>{liq}</td><td>场内成交{fund.get('market_amount', 0):.1f}万元</td></tr>")
        html_parts.append(f"<tr><td>估值误差风险</td><td class='{risk_class(est)}'>{est}</td><td>算法：{nav_est.get('algorithm', '未知')}，置信度{nav_est.get('confidence', 0):.0%}</td></tr>")
        html_parts.append(f"<tr><td>时间差风险</td><td class='{risk_class(tm)}'>{tm}</td><td>T+2套利周期净值波动风险</td></tr>")
        html_parts.append("</table>")

        # 建议
        html_parts.append(f"<div class='suggestion'><b>建议：</b>{signal.get('suggestion', '')}</div>")

        html_parts.append("</div>")  # fund-card

    # 风险提示
    html_parts.append("<div class='footer'>")
    html_parts.append("<h3>风险提示</h3>")
    html_parts.append("<p>1. 本报告仅供参考，不构成任何投资建议。</p>")
    html_parts.append("<p>2. LOF套利存在时间差风险、流动性风险、估值偏差风险等多种风险。</p>")
    html_parts.append("<p>3. 套利需T+2完成，期间净值和场内价格均可能发生大幅波动。</p>")
    html_parts.append("<p>4. 请充分了解交易规则和风险后审慎决策。</p>")
    html_parts.append("</div>")

    html_parts.append("</div></body></html>")
    return "\n".join(html_parts)


def save_report(analysis_result: Dict, output_path: str, fmt: str = "text") -> str:
    """
    保存报告到文件

    Args:
        analysis_result: 分析结果
        output_path: 输出文件路径
        fmt: 格式："text" / "json" / "html"

    Returns:
        实际保存的文件路径
    """
    if fmt == "json":
        content = generate_json_report(analysis_result)
    elif fmt == "html":
        content = generate_simple_html_report(analysis_result)
    else:
        content = generate_text_report(analysis_result)

    with open(output_path, "w", encoding="utf-8") as f:
        f.write(content)

    return output_path
