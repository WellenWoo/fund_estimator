"""天天基金官方盘中估值 —— 仅做交叉校验。

接口（github_code.md §7.1 / §9）::

    http://fundgz.1234567.com.cn/js/{code}.js

返回 JSONP::

    jsonpgz({"fundcode":"160223","name":"...","jzrq":"2026-07-10",
             "dwjz":"2.1318","gsz":"2.0657","gszzl":"-3.10","gztime":"2026-07-13 15:00"});

字段：
- dwjz   T-1 单位净值
- gsz    官方盘中估值
- gszzl  官方估值涨跌幅(%)
- jzrq   净值日期
- gztime 估值时间

本模块**不参与主估值链路**，只用于把自研估算值与「官方估值」做交叉校验
（README §2「不是从网站抄官方估值，而是自己算」）。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Optional

from ..cache import http_get


FUNDGZ_URL = "http://fundgz.1234567.com.cn/js/{code}.js"
REFERER = "http://fund.eastmoney.com/"

_JSONP_RE = re.compile(r"jsonpgz\((?P<json>\{.*\})\)\s*;?", re.S)


@dataclass
class TiantianEstimate:
    """天天基金官方盘中估值快照。"""

    fund_code: str
    name: str
    jzrq: str            # T-1 净值日期
    dwjz: float          # T-1 单位净值
    gsz: float           # 官方估值
    gszzl: float         # 官方估值涨跌幅 %
    gztime: str          # 估值时间

    def to_dict(self) -> dict:
        return {
            "fund_code": self.fund_code,
            "name": self.name,
            "jzrq": self.jzrq,
            "dwjz": self.dwjz,
            "gsz": self.gsz,
            "gszzl": self.gszzl,
            "gztime": self.gztime,
        }


def fetch_official_estimate(fund_code: str) -> Optional[TiantianEstimate]:
    """抓取天天基金官方盘中估值。失败返回 None。"""
    url = FUNDGZ_URL.format(code=fund_code)
    try:
        text = http_get(url, encoding="utf-8", referer=REFERER)
    except RuntimeError:
        return None
    m = _JSONP_RE.search(text)
    if not m:
        return None
    try:
        data = json.loads(m.group("json"))
    except json.JSONDecodeError:
        return None

    def _f(v: str) -> float:
        try:
            return float(v)
        except (TypeError, ValueError):
            return 0.0

    return TiantianEstimate(
        fund_code=data.get("fundcode", fund_code),
        name=data.get("name", ""),
        jzrq=data.get("jzrq", ""),
        dwjz=_f(data.get("dwjz")),
        gsz=_f(data.get("gsz")),
        gszzl=_f(data.get("gszzl")),
        gztime=data.get("gztime", ""),
    )


__all__ = ["TiantianEstimate", "fetch_official_estimate"]
