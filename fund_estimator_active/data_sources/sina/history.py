"""data_sources/sina/history.py — 新浪历史 K 线

通过 CN_MarketData.getKLineData 拉日 K 线 (money.finance.sina.com.cn 是稳定入口)。
本地缓存 .cache/kline_{code}.csv
"""
from __future__ import annotations
import re
import json
import time
import urllib.request
from datetime import date as Date, timedelta
from typing import Optional

from data_sources import cache


def _sina_symbol(code: str) -> str:
    """6 位代码 → sh/sz 前缀。接受 6 位代码或已加前缀。"""
    if code.startswith(("sh", "sz")):
        return code
    if code.startswith(("60", "68", "11", "13", "5")):
        return f"sh{code}"
    return f"sz{code}"


def fetch_kline(code: str, scale_days: int = 240, force: bool = False,
                timeout: int = 15) -> list[dict]:
    """拉日 K 线, 缓存到本地。

    Args:
        code: 6 位代码 (股票 / 指数) 或 sh/sz 前缀
        scale_days: 拉取最近 N 天
    """
    sina_sym = _sina_symbol(code)
    cache_name = f"kline_{sina_sym}"
    if not force and cache.is_fresh(cache_name):
        rows = cache.load_rows(cache_name)
        out = []
        for r in rows:
            r2 = dict(r)
            for k in ("date",):
                if r2.get(k):
                    try:
                        r2[k] = Date.fromisoformat(r2[k])
                    except Exception:
                        pass
            for k in ("open", "high", "low", "close", "volume", "amount"):
                if r2.get(k):
                    try:
                        r2[k] = float(r2[k])
                    except Exception:
                        r2[k] = 0.0
            out.append(r2)
        if out and len(out) >= scale_days * 0.8:
            return out[-scale_days:]

    # 通过 CN_MarketData 拉 (money.finance.sina.com.cn)
    symbol = sina_sym
    url = (
        f"http://money.finance.sina.com.cn/quotes_service/api/json_v2.php/CN_MarketData.getKLineData"
        f"?symbol={symbol}&scale=240&ma=no&datalen={scale_days + 30}"
    )
    req = urllib.request.Request(url, headers={
        "Referer": "https://finance.sina.com.cn/",
        "User-Agent": "Mozilla/5.0",
    })

    raw_rows: list[dict] = []
    last_err: Optional[Exception] = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read().decode("utf-8", errors="ignore")
            data = json.loads(raw)
            if isinstance(data, dict):
                data = data.get("data", data)
            if isinstance(data, list) and data:
                for r in data:
                    raw_rows.append({
                        "date": r.get("day"),
                        "open": float(r.get("open", 0) or 0),
                        "high": float(r.get("high", 0) or 0),
                        "low": float(r.get("low", 0) or 0),
                        "close": float(r.get("close", 0) or 0),
                        "volume": float(r.get("volume", 0) or 0),
                        "amount": float(r.get("amount", 0) or 0),
                    })
                break
        except Exception as e:
            last_err = e
            time.sleep(0.5)

    if not raw_rows:
        print(f"[kline] {code} fetch failed: {last_err!r}")
        rows = cache.load_rows(cache_name)
        return [dict(r) for r in rows[-scale_days:]] if rows else []

    if raw_rows:
        cache.save_rows(cache_name, raw_rows,
                        fieldnames=["date", "open", "high", "low", "close", "volume", "amount"])
        return raw_rows[-scale_days:]
    return []


def get_close_on(code: str, target_date: Date) -> Optional[float]:
    """取某日收盘价。"""
    rows = fetch_kline(code, scale_days=300)
    for r in rows:
        if r.get("date") == target_date:
            return r.get("close")
    return None


def get_return_pct(code: str, start: Date, end: Date) -> Optional[float]:
    """区间涨跌幅 (decimal)。"""
    rows = fetch_kline(code, scale_days=400)
    start_close = end_close = None
    for r in rows:
        d = r.get("date")
        if d == start:
            start_close = r.get("close")
        if d == end:
            end_close = r.get("close")
    if start_close and end_close and start_close > 0:
        return (end_close - start_close) / start_close
    return None
