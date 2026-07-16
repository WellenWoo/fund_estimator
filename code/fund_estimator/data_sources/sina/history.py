"""新浪历史日线接口（GBK → UTF-8）。

URL: https://quotes.sina.cn/cn/api/jsonp_v2.php/var=/CN_MarketDataService.getKLineData
     ?symbol=sz300750&scale=240&datalen=20&ma=no

返回：JSONP, 形如：
    var=([{"day":"2026-06-08","open":"395.800","high":"402.680","low":"390.700","close":"393.020","volume":"28652636"}, ...])

本地缓存：所有拉到的日线会落盘 .cache/kline_{symbol}.csv，便于反复回测。
"""

from __future__ import annotations

import json
import re
import sys
import urllib.parse
import urllib.request
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

# 让 `import cache` 生效
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))
from fund_estimator.data_sources.cache import read_csv, write_csv  # noqa: E402

URL = "https://quotes.sina.cn/cn/api/jsonp_v2.php/var=/CN_MarketDataService.getKLineData"
HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Referer": "https://finance.sina.com.cn/",
}


def _fetch_kline_raw(symbol: str, datalen: int, scale: int) -> list[dict]:
    import time
    params = {
        "symbol": symbol,
        "scale": str(scale),  # 240 = daily
        "datalen": str(datalen),
        "ma": "no",
    }
    url = URL + "?" + urllib.parse.urlencode(params)

    last_err: Optional[Exception] = None
    for attempt in range(4):
        req = urllib.request.Request(url, headers=HEADERS)
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                raw = resp.read().decode("gbk", errors="ignore")
        except Exception as e:
            last_err = e
            time.sleep(1.0 + attempt * 0.5)
            continue

        m = re.search(r"\(\s*(\[.*?\])\s*\)\s*;?", raw, re.S)
        if not m:
            # Sina 偶发返回 var=(null); 的限流响应，退避重试
            if "null" in raw or "<script>" in raw.lower():
                time.sleep(1.0 + attempt * 0.5)
                continue
            raise RuntimeError(f"unparseable: {raw[:200]}")
        # eval careful — data is JSON-like but keys are unquoted in JSONP output
        # 转 JSON：手动加引号
        text = m.group(1)
        text = text.replace("'", '"')
        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            raise RuntimeError(f"json decode failed: {e}; raw={text[:200]}")
    raise RuntimeError(f"sina fetch failed after retries: {last_err}")


def fetch_kline(symbol: str, days: int = 60, force: bool = False) -> list[dict]:
    """返回最近的 N 个交易日的 OHLCV 列表，按日期升序。带本地缓存。"""
    cache_name = f"kline_{symbol}.csv"
    if not force:
        cached = read_csv(cache_name)
        if cached:
            # 取最后 N 条
            return cached[-days:] if len(cached) > days else cached

    raw = _fetch_kline_raw(symbol, days, 240)
    out = []
    for row in raw:
        try:
            out.append(
                {
                    "date": row["day"],
                    "open": row["open"],
                    "high": row["high"],
                    "low": row["low"],
                    "close": row["close"],
                    "volume": row["volume"],
                }
            )
        except (KeyError, ValueError, TypeError):
            continue
    out.sort(key=lambda r: r["date"])
    if out:
        try:
            write_csv(cache_name, out)
        except Exception:
            pass
    return out


def get_close(symbol: str, day: str) -> Optional[float]:
    """获取某交易日的收盘价（day 形如 '2026-07-06'）。带本地缓存。"""
    # 先查缓存
    cache_name = f"kline_{symbol}.csv"
    cached = read_csv(cache_name)
    if cached:
        for k in cached:
            if k["date"] == day:
                return float(k["close"])
    # 没有再拉网络
    for window in (60, 120, 252):
        try:
            klines = fetch_kline(symbol, window)
        except Exception:
            continue
        for k in klines:
            if k["date"] == day:
                return float(k["close"])
    return None


if __name__ == "__main__":
    import sys
    sym = sys.argv[1] if len(sys.argv) > 1 else "sz300750"
    days = int(sys.argv[2]) if len(sys.argv) > 2 else 10
    rows = fetch_kline(sym, days)
    print(f"=== {sym} 最近 {days} 个交易日 ===")
    for r in rows:
        print(f"{r['date']}  open={r['open']}  high={r['high']}  low={r['low']}  close={r['close']}  vol={r['volume']}")
