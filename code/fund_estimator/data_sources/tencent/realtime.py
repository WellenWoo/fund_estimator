"""腾讯财经实时行情（GBK 编码），作为新浪接口的备选。

URL: https://qt.gtimg.cn/q=sz300750
格式：
    v_sz300750="51~宁德时代~300750~374.51~380.00~379.23~...~";

字段索引（公开约定）:
    1  名字
    3  当前价
    4  今开
    5  昨收
    ... (32) 涨跌幅 %
    (30) 时间戳
"""

from __future__ import annotations

from datetime import datetime
from typing import Iterable
from urllib.request import Request, urlopen

from ...core.models import RealtimeQuote

URL = "https://qt.gtimg.cn/q={symbols}"
HEADERS = {"User-Agent": "Mozilla/5.0"}


def _split_tencent_payload(payload: str) -> list[str]:
    """腾讯的 v_ 前缀格式用 ~ 分隔字段。"""
    inner = payload.split("=", 1)[1].strip().strip('"').strip(";")
    return inner.split("~")


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
        if not line.startswith("v_"):
            continue
        try:
            fields = _split_tencent_payload(line)
            if len(fields) < 35:
                continue
            # "sz300750" -> ("SZ", "300750")
            symbol = line.split("=", 1)[0].replace("v_", "").strip()
            market = "SZ" if symbol.startswith("sz") else "SH"
            code = symbol[2:]

            ts_str = fields[30] if len(fields) > 30 else ""
            try:
                ts = datetime.strptime(ts_str, "%Y%m%d%H%M%S")
            except ValueError:
                ts = datetime.now()

            out.append(
                RealtimeQuote(
                    code=code,
                    market=market,
                    name=fields[1],
                    price=float(fields[3] or 0),
                    open=float(fields[5] or 0),
                    prev_close=float(fields[4] or 0),
                    timestamp=ts,
                )
            )
        except Exception:
            continue
    return out


if __name__ == "__main__":
    import sys
    codes = sys.argv[1:] if len(sys.argv) > 1 else ["sz300750", "sh600519"]
    qs = fetch_quotes(codes)
    for q in qs:
        print(f"{q.market}{q.code} {q.name} 现价={q.price} 昨收={q.prev_close} 涨跌={q.change_pct:.2f}%")
