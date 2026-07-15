"""腾讯备用实时行情 —— ``qt.gtimg.cn``（GBK 编码）。

接口::

    http://qt.gtimg.cn/q=sz399006,sz300750,sh600519

返回每行形如::

    v_sz399006="51~创业板指~399006~2100.00~2050.00~...";

字段以 ``~`` 分隔（股票）：
    [0]市场 [1]名称 [2]代码 [3]当前价 [4]昨收 [5]今开 ... [30]时间戳 [31]涨跌 [32]涨跌% [33]最高 [34]最低 ...

作为新浪 hq.sinajs.cn 的容灾备份（README §10：多源容灾）。
"""

from __future__ import annotations

import re
from typing import Iterable, Optional

from ..cache import http_get
from ...core.models import RealtimeQuote


TENCENT_URL = "http://qt.gtimg.cn/q={codes}"
REFERER = "https://gu.qq.com"

_LINE_RE = re.compile(r'v_(?P<code>\w+)="(?P<body>[^"]*)";')


def _parse(code: str, parts: list[str]) -> Optional[RealtimeQuote]:
    if len(parts) < 6:
        return None
    try:
        price = float(parts[3] or 0)
        prev_close = float(parts[4] or 0)
        open_ = float(parts[5] or 0)
        high = float(parts[33]) if len(parts) > 33 and parts[33] else 0.0
        low = float(parts[34]) if len(parts) > 34 and parts[34] else 0.0
        volume = float(parts[6]) if len(parts) > 6 and parts[6] else 0.0
        amount = float(parts[37]) if len(parts) > 37 and parts[37] else 0.0
        ts = parts[30] if len(parts) > 30 else ""
        date, time = "", ""
        if len(ts) >= 14:  # YYYYMMDDHHMMSS
            date = f"{ts[0:4]}-{ts[4:6]}-{ts[6:8]}"
            time = f"{ts[8:10]}:{ts[10:12]}:{ts[12:14]}"
        return RealtimeQuote(
            code=code,
            name=parts[1],
            price=price,
            prev_close=prev_close,
            open=open_,
            high=high,
            low=low,
            volume=volume,
            amount=amount,
            date=date,
            time=time,
        )
    except (ValueError, IndexError):
        return None


def fetch_realtime(codes: Iterable[str]) -> dict[str, RealtimeQuote]:
    """批量抓取腾讯实时行情，返回 code -> RealtimeQuote。"""
    codes = [c for c in codes if c]
    if not codes:
        return {}
    url = TENCENT_URL.format(codes=",".join(codes))
    text = http_get(url, encoding="gbk", referer=REFERER)

    out: dict[str, RealtimeQuote] = {}
    for m in _LINE_RE.finditer(text):
        code = m.group("code")
        body = m.group("body")
        if not body:
            continue
        parts = body.split("~")
        q = _parse(code, parts)
        if q:
            out[code] = q
    return out
