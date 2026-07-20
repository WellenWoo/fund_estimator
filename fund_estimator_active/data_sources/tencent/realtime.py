"""data_sources/tencent/realtime.py — 腾讯实时行情 (备用)"""
from __future__ import annotations
import urllib.request
from datetime import datetime

from core.models import RealtimeQuote


def _gbk(url: str, timeout: int = 10) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("gbk", errors="ignore")


def fetch_quotes(codes: list[str], timeout: int = 10) -> dict[str, RealtimeQuote]:
    """腾讯实时 (GBK)。"""
    tx_codes = []
    for c in codes:
        if c.startswith(("60", "68", "11", "13", "5")):
            tx_codes.append(f"sh{c}")
        else:
            tx_codes.append(f"sz{c}")
    url = f"http://qt.gtimg.cn/q={','.join(tx_codes)}"
    raw = _gbk(url, timeout)

    results: dict[str, RealtimeQuote] = {}
    for line in raw.split(";"):
        if '="' not in line:
            continue
        try:
            head, body = line.split('="', 1)
            body = body.rstrip('";\n')
            fields = body.split("~")
            # 0=未知 1=名称 2=代码 3=现价 4=昨收 5=今开 6=成交量(手)...
            name = fields[1] if len(fields) > 1 else ""
            code = fields[2] if len(fields) > 2 else ""
            code = code.replace("sh", "").replace("sz", "") if code else ""
            price = float(fields[3] or 0) if len(fields) > 3 else 0
            prev_close = float(fields[4] or 0) if len(fields) > 4 else 0
            change_pct = (price - prev_close) / prev_close if prev_close > 0 else 0.0
            results[code] = RealtimeQuote(
                code=code, name=name, prev_close=prev_close, price=price,
                change_pct=change_pct,
                timestamp=datetime.now().isoformat(),
            )
        except Exception:
            continue
    return results
