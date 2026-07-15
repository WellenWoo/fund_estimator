"""新浪实时行情 —— ``hq.sinajs.cn``（GBK 编码）。

接口::

    http://hq.sinajs.cn/list=sz399006,sz300750,sh600519

返回每行形如::

    var hq_str_sz399006="创业板指,2100.00,2050.00,2020.00,...";

字段（股票）：名称,今开,昨收,当前价,最高,最低,买一,卖一,成交量,成交额,...,日期,时间。
指数字段略有不同：名称,当前点位,涨跌额,涨跌幅,成交量,成交额。

新浪需要 Referer=https://finance.sina.com.cn 才不被拒。
"""

from __future__ import annotations

import re
from typing import Iterable, Optional

from ..cache import http_get
from ...core.models import RealtimeQuote


SINA_URL = "http://hq.sinajs.cn/list={codes}"
REFERER = "https://finance.sina.com.cn"

_LINE_RE = re.compile(r'var hq_str_(?P<code>\w+)="(?P<body>[^"]*)";')


def _parse_stock(code: str, parts: list[str]) -> Optional[RealtimeQuote]:
    """解析股票行情行（>=32 字段）。"""
    if len(parts) < 32:
        return None
    try:
        return RealtimeQuote(
            code=code,
            name=parts[0],
            open=float(parts[1] or 0),
            prev_close=float(parts[2] or 0),
            price=float(parts[3] or 0),
            high=float(parts[4] or 0),
            low=float(parts[5] or 0),
            volume=float(parts[8] or 0),
            amount=float(parts[9] or 0),
            date=parts[30],
            time=parts[31],
        )
    except (ValueError, IndexError):
        return None


def _parse_index(code: str, parts: list[str]) -> Optional[RealtimeQuote]:
    """解析指数行情行（新浪指数：名称,当前点位,涨跌额,涨跌幅,成交量(手),成交额)。"""
    if len(parts) < 4:
        return None
    try:
        price = float(parts[1] or 0)
        change = float(parts[2] or 0)
        prev_close = price - change
        return RealtimeQuote(
            code=code,
            name=parts[0],
            price=price,
            prev_close=prev_close,
            volume=float(parts[4]) if len(parts) > 4 and parts[4] else 0.0,
            amount=float(parts[5]) if len(parts) > 5 and parts[5] else 0.0,
        )
    except (ValueError, IndexError):
        return None


def _is_index(code: str) -> bool:
    # 常见指数：sz399xxx / sh000xxx / bj899xxx
    body = code[2:] if code[:2] in ("sh", "sz", "bj") else code
    return body.startswith(("399", "000")) and code.startswith(("sz", "sh"))


def fetch_realtime(codes: Iterable[str]) -> dict[str, RealtimeQuote]:
    """批量抓取实时行情。

    Parameters
    ----------
    codes:
        标准化代码列表，例如 ``["sz399006", "sz300750"]``。

    Returns
    -------
    dict[str, RealtimeQuote]
        code -> quote。
    """
    codes = [c for c in codes if c]
    if not codes:
        return {}
    url = SINA_URL.format(codes=",".join(codes))
    text = http_get(url, encoding="gbk", referer=REFERER)

    out: dict[str, RealtimeQuote] = {}
    for m in _LINE_RE.finditer(text):
        code = m.group("code")
        body = m.group("body")
        if not body:
            continue
        parts = body.split(",")
        # 新浪对 sh/sz 前缀的指数与个股一样使用「32 字段股票格式」
        # （name,open,prev_close,price,high,low,...,date,time）。
        # 只有极少数精简接口才用短格式，这里按字段数自动判别。
        if len(parts) >= 32:
            quote = _parse_stock(code, parts)
        elif _is_index(code):
            quote = _parse_index(code, parts)
        else:
            quote = _parse_stock(code, parts)
        if quote:
            out[code] = quote
    return out
