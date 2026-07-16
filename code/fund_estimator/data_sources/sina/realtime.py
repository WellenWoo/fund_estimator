"""新浪财经实时行情接口（GBK 编码）。

URL: https://hq.sinajs.cn/list=sz300750,sh600519,...

实测字段索引（基于 2026-07-07 09:22 Asia/Shanghai 的 SZ300750 返回值）：
    0  名字          "宁德时代"
    1  今开          0.000
    2  昨收          374.510
    3  当前价         0.000   (盘前/收盘后是 0)
    4  今日最高       0.000
    5  今日最低       0.000
    6  竞买价(买一)   379.000
    7  竞卖价(卖一)   379.000
    ...
   30  日期           "2026-07-07"
   31  时间           "09:22:51"
   32 行情时间戳小数  "00"

注意点：
- 盘前/收盘后：3-5 字段为 0；但 2 (昨收) 一直稳定。
- 涨跌停板预挂的买卖盘：6/7 字段有值（实际当前价在集合竞价后才稳定下来）。

我们采用兜底策略：
  - 如果现价 = 0 且买卖盘有值，用 (买一+卖一)/2 作为临时现价；
  - 如果全为 0（盘前太早），用昨收作为兜底（涨跌 = 0）。
"""

from __future__ import annotations

from datetime import datetime
from typing import Iterable
from urllib.request import Request, urlopen

from ...core.models import RealtimeQuote

URL = "https://hq.sinajs.cn/list={symbols}"
HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Referer": "https://finance.sina.com.cn",
}

# 字段索引
IDX_NAME = 0
IDX_OPEN = 1
IDX_PREV_CLOSE = 2
IDX_PRICE = 3
IDX_HIGH = 4
IDX_LOW = 5
IDX_BID1 = 6
IDX_ASK1 = 7
IDX_DATE = 30
IDX_TIME = 31


def _market_from_symbol(symbol: str) -> tuple[str, str]:
    s = symbol.lower()
    if s.startswith("sh"):
        return "SH", s[2:]
    if s.startswith("sz"):
        return "SZ", s[2:]
    raise ValueError(f"unknown symbol prefix: {symbol}")


def _safe_float(s: str) -> float:
    try:
        return float(s)
    except (TypeError, ValueError):
        return 0.0


def fetch_quotes(symbols: Iterable[str], timeout: float = 10.0) -> list[RealtimeQuote]:
    sym_list = list(symbols)
    if not sym_list:
        return []
    url = URL.format(symbols=",".join(sym_list))
    req = Request(url, headers=HEADERS)
    with urlopen(req, timeout=timeout) as resp:
        raw = resp.read().decode("gbk", errors="ignore")

    out: list[RealtimeQuote] = []
    for line in raw.splitlines():
        line = line.strip()
        if not line.startswith("var hq_str_"):
            continue
        try:
            head, body = line.split("=", 1)
            symbol = head.replace("var hq_str_", "").strip()
            body = body.strip().rstrip(";").strip().strip('"')
            fields = body.split(",")
            if len(fields) < 33:
                continue
            market, code = _market_from_symbol(symbol)
            ts_str = f"{fields[IDX_DATE]}T{fields[IDX_TIME]}"
            try:
                ts = datetime.strptime(ts_str, "%Y-%m-%dT%H:%M:%S")
            except ValueError:
                ts = datetime.now()

            prev_close = _safe_float(fields[IDX_PREV_CLOSE])
            price = _safe_float(fields[IDX_PRICE])

            # 兜底：盘前/收盘后用 (买一+卖一)/2
            if price <= 0 and prev_close > 0:
                bid1 = _safe_float(fields[IDX_BID1])
                ask1 = _safe_float(fields[IDX_ASK1])
                if bid1 > 0 and ask1 > 0:
                    price = (bid1 + ask1) / 2.0
                else:
                    price = prev_close  # 涨跌=0

            out.append(
                RealtimeQuote(
                    code=code,
                    market=market,
                    name=fields[IDX_NAME],
                    open=_safe_float(fields[IDX_OPEN]),
                    prev_close=prev_close,
                    price=price,
                    high=_safe_float(fields[IDX_HIGH]),
                    low=_safe_float(fields[IDX_LOW]),
                    timestamp=ts,
                )
            )
        except Exception:
            continue
    return out


def build_symbol(market: str, code: str) -> str:
    """('SZ', '300750') -> 'sz300750'"""
    return f"{market.lower()}{code}"


if __name__ == "__main__":
    import sys
    codes = sys.argv[1:] if len(sys.argv) > 1 else ["sz300750", "sh600519"]
    qs = fetch_quotes(codes)
    for q in qs:
        print(f"{q.market}{q.code} {q.name} 现价={q.price} 昨收={q.prev_close} 涨跌={q.change_pct:.2f}%")
