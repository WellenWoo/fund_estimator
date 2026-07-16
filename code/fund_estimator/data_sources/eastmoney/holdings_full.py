"""东方财富基金持仓明细（季报/半年报/年报）。

URL 模式:
    http://fundf10.eastmoney.com/FundArchivesDatas.aspx?type=jjcc&code=160223&topline=10&year=2026&month=3

返回: HTML 内的 apidata = {content: "...<table>...</table>..."};

解析后得到字段：股票代码 / 名称 / 占净值比例(%) / 持股数(万股) / 持仓市值(万元)
"""

from __future__ import annotations

import re
import urllib.parse
import urllib.request
from datetime import date

BASE_URL = "http://fundf10.eastmoney.com/FundArchivesDatas.aspx"
HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Referer": "https://fundf10.eastmoney.com/",
}


def fetch_holdings_html(fund_code: str, year: int, month: int, topline: int = 10) -> str:
    """拉取某基金某报告期的股票持仓表格 HTML 片段。"""
    params = {"type": "jjcc", "code": fund_code, "topline": str(topline), "year": str(year), "month": str(month)}
    url = BASE_URL + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=20) as resp:
        raw = resp.read().decode("utf-8", errors="ignore")
    return raw


def parse_holdings(html: str) -> tuple[date, list[dict]]:
    """从 html 中抽取 (报告截止日, 持仓列表)。"""
    # 报告日: <font class='px12'>YYYY-MM-DD</font>
    m_date = re.search(r"<font class='px12'>(\d{4}-\d{2}-\d{2})</font>", html)
    if not m_date:
        raise ValueError("no report date found in HTML")
    report_date = date.fromisoformat(m_date.group(1))
    # 行: <tr><td>序号</td><td><a ...>代码</a></td>...<td class='tor'>占比%</td><td>股数万股</td><td>市值万元</td></tr>
    holdings: list[dict] = []
    row_re = re.compile(
        r"<tr>\s*<td>\d+</td>\s*<td>\s*<a[^>]*>(\d{6})</a>\s*</td>\s*<td[^>]*>\s*<a[^>]*>([^<]+)</a>.*?"
        r"<td class='tor'>\s*([\d.]+)\s*%\s*</td>\s*<td class='tor'>\s*([\d.]+)\s*</td>\s*"
        r"<td class='tor'>\s*([\d,\.]+)\s*</td>\s*</tr>",
        re.S,
    )
    for m in row_re.finditer(html):
        code, name, pct, shares, mv = m.groups()
        holdings.append(
            {
                "code": code,
                "name": name.strip(),
                "weight_pct": float(pct),
                "shares_wan": float(shares),
                "mv_wan": float(mv.replace(",", "")),
            }
        )
    return report_date, holdings


def fetch_holdings(fund_code: str, year: int, month: int, topline: int = 10) -> tuple[date, list[dict]]:
    """一站式：拉取 + 解析。"""
    html = fetch_holdings_html(fund_code, year, month, topline)
    return parse_holdings(html)


if __name__ == "__main__":
    import sys
    code = sys.argv[1] if len(sys.argv) > 1 else "160223"
    year = int(sys.argv[2]) if len(sys.argv) > 2 else 2026
    month = int(sys.argv[3]) if len(sys.argv) > 3 else 3
    report_date, hs = fetch_holdings(code, year, month)
    print(f"=== {code} 2026{month} 季报 截止 {report_date} ===")
    total = 0.0
    for h in hs:
        print(f"  {h['code']} {h['name']:6s} 占净值 {h['weight_pct']:>5.2f}%  持股 {h['shares_wan']:>8.2f} 万")
        total += h["weight_pct"]
    print(f"Top10 累计: {total:.2f}%")
