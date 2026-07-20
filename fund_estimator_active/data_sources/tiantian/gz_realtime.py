"""data_sources/tiantian/gz_realtime.py — 天天基金官方估值 (参考)

注意: 这是"基金公司的官方估值", 不能用作我们自己的算法输入,
但可以做交叉校验和残差分析。
"""
from __future__ import annotations
import re
import urllib.request
import json
from typing import Optional


def fetch_tiantian_gz(fund_code: str = "160211", timeout: int = 10) -> Optional[dict]:
    """拉取天天基金官方估值 JSONP。

    Returns:
        dict: {"fundcode", "name", "jzrq", "dwjz", "gsz", "gszzl", "gztime"}
    """
    url = f"http://fundgz.1234567.com.cn/js/{fund_code}.js?rt={__import__('time').time()}"
    req = urllib.request.Request(url, headers={"Referer": "http://fund.eastmoney.com/",
                                                "User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", errors="ignore")
    except Exception:
        return None
    m = re.search(r"jsonpgz\((.*)\)\s*;?\s*$", raw.strip())
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except Exception:
        return None
