"""data_sources/sina/realtime.py — 新浪实时行情 (GBK)

API: hq.sinajs.cn/list=sh600519,sz000001
字段(GBK): 0=名称, 1=今开, 2=昨收, 3=现价, 4=最高, 5=最低, ...
"""
from __future__ import annotations
import urllib.request
from datetime import datetime

from core.models import RealtimeQuote


def _gbk_list(url: str, timeout: int = 10) -> list[str]:
    req = urllib.request.Request(url, headers={
        "Referer": "https://finance.sina.com.cn/",
        "User-Agent": "Mozilla/5.0",
    })
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
    return raw.decode("gbk", errors="ignore").split(";")


def fetch_quotes(codes: list[str], timeout: int = 10) -> dict[str, RealtimeQuote]:
    """批量拉取实时行情。

    Args:
        codes: 6 位股票代码列表 (e.g. ["000688", "600519"])

    Returns:
        {code: RealtimeQuote}
    """
    sina_codes = []
    for c in codes:
        if c.startswith(("60", "68", "11", "13", "5")):
            sina_codes.append(f"sh{c}")
        else:
            sina_codes.append(f"sz{c}")
    url = f"http://hq.sinajs.cn/list={','.join(sina_codes)}"

    results: dict[str, RealtimeQuote] = {}
    for line in _gbk_list(url, timeout):
        if '="' not in line:
            continue
        try:
            head, body = line.split('="', 1)
            body = body.rstrip('";\n')
            fields = body.split(",")
            sina_code = head.split("_")[-1]
            code = sina_code[2:]  # 去掉 sh/sz
            # fields: [name, open, prev_close, price, high, low, ...]
            name = fields[0]
            prev_close = float(fields[2] or 0)
            price = float(fields[3] or 0)
            change_pct = (price - prev_close) / prev_close if prev_close > 0 else 0.0
            results[code] = RealtimeQuote(
                code=code, name=name, prev_close=prev_close, price=price,
                change_pct=change_pct,
                timestamp=datetime.now().isoformat(),
            )
        except Exception:
            continue
    return results
