"""新浪历史 K 线 —— ``CN_MarketDataService.getKLineData``。

接口::

    https://quotes.sina.cn/cn/api/json_v2.php/CN_MarketDataService.getKLineData
        ?symbol=sz399006&scale=240&ma=no&datalen=1023

返回 JSON 数组，每项 ``{day, open, high, low, close, volume}``。
- scale=240 表示日线（240 分钟）。
- symbol 用 ``sz399006`` / ``sz300750`` / ``sh600519`` 这种带前缀格式。

这是 ITERATIONS.md 的历史股票/指数日线来源，回测用它取每个交易日的收盘价。
"""

from __future__ import annotations

import json
import re
from typing import Optional

from ..cache import CsvCache, http_get


KLINE_URL = (
    "https://quotes.sina.cn/cn/api/json_v2.php/CN_MarketDataService.getKLineData"
    "?symbol={symbol}&scale=240&ma=no&datalen={datalen}"
)
REFERER = "https://finance.sina.com.cn"

_JSON_ARRAY_RE = re.compile(r"\[.*\]", re.S)


def _parse_kline(text: str) -> list[dict]:
    m = _JSON_ARRAY_RE.search(text)
    if not m:
        return []
    try:
        arr = json.loads(m.group(0))
    except json.JSONDecodeError:
        return []
    rows = []
    for it in arr:
        day = it.get("day", "")
        # 新浪 day 可能是 "2026-07-14" 或含时间
        date = day.split(" ")[0] if day else ""
        try:
            rows.append(
                {
                    "date": date,
                    "open": float(it.get("open", 0)),
                    "high": float(it.get("high", 0)),
                    "low": float(it.get("low", 0)),
                    "close": float(it.get("close", 0)),
                    "volume": float(it.get("volume", 0)),
                }
            )
        except (TypeError, ValueError):
            continue
    return rows


def fetch_kline(
    symbol: str,
    datalen: int = 1023,
    *,
    cache: Optional[CsvCache] = None,
    force: bool = False,
) -> list[dict]:
    """抓取日线 K 线，返回按日期升序的 list[dict]。

    symbol 例：``sz399006`` / ``sz300750``。
    """
    cache = cache or CsvCache()

    def _fetch() -> list[dict]:
        url = KLINE_URL.format(symbol=symbol, datalen=datalen)
        text = http_get(url, encoding="utf-8", referer=REFERER)
        return _parse_kline(text)

    rows = cache.get_or_fetch(
        namespace="kline",
        key=symbol,
        fetch=_fetch,
        fieldnames=["date", "open", "high", "low", "close", "volume"],
        force=force,
    )
    out = []
    for r in rows:
        try:
            out.append(
                {
                    "date": r["date"],
                    "open": float(r["open"]),
                    "high": float(r["high"]),
                    "low": float(r["low"]),
                    "close": float(r["close"]),
                    "volume": float(r["volume"]),
                }
            )
        except (TypeError, ValueError):
            continue
    return sorted(out, key=lambda r: r["date"])


def close_on(symbol: str, date: str, *, cache: Optional[CsvCache] = None) -> Optional[float]:
    """返回某 symbol 在指定交易日的收盘价；非交易日返回 None。"""
    rows = fetch_kline(symbol, cache=cache)
    for r in rows:
        if r["date"] == date:
            return r["close"]
    return None


def close_on_in_window(
    symbol: str,
    date: str,
    *,
    cache: Optional[CsvCache] = None,
) -> Optional[float]:
    """返回 <=date 的最近一个交易日收盘价。

    ITERATIONS.md 提到的 bug：非交易日直接 close_on 会返回 None 导致 TypeError，
    这里返回窗口内最近收盘价供上层判断是否交易日。
    """
    rows = fetch_kline(symbol, cache=cache)
    prev = None
    for r in rows:
        if r["date"] <= date:
            prev = r["close"]
        else:
            break
    return prev


def trading_days(symbol: str, *, cache: Optional[CsvCache] = None) -> list[str]:
    """返回该 symbol 有日线的全部交易日（升序）。"""
    return [r["date"] for r in fetch_kline(symbol, cache=cache)]
