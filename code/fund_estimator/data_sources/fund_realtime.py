# -*- coding: utf-8 -*-
"""
LOF 场内实时交易价格获取模块

数据源：
  1. 腾讯行情 (qt.gtimg.cn) - 场内实时价格、成交量、涨跌幅
  2. 天天基金 (fundgz.1234567.com.cn) - 估算净值、估算涨幅

用途：
  对比场内价格 vs 估算净值，计算溢价率/折价率，辅助 LOF 套利决策。
"""

from __future__ import annotations

import os
import re
import sys
import time
from dataclasses import dataclass, asdict
from typing import Optional, Dict

try:
    from .cache import http_get
except ImportError:
    from cache import http_get


# ====================================================================
# 数据模型
# ====================================================================

@dataclass
class IntradayQuote:
    """LOF 场内实时行情快照（来自腾讯/新浪）。"""
    fund_code: str          # 基金代码, 如 "160223"
    fund_name: str          # 基金名称
    price: float = 0.0      # 最新场内成交价（元）
    prev_close: float = 0.0 # 上一交易日收盘价
    open_: float = 0.0      # 今日开盘价
    high: float = 0.0       # 今日最高价
    low: float = 0.0        # 今日最低价
    volume: int = 0         # 成交量（股）
    amount: float = 0.0     # 成交额（元）
    change_pct: float = 0.0 # 涨跌幅（%）
    date: str = ""          # 行情日期
    time: str = ""          # 行情时间

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class FundEstimate:
    """基金估算净值（来自天天基金 fundgz）。"""
    fund_code: str
    fund_name: str
    estimated_nav: float = 0.0    # 估算净值
    estimated_change_pct: float = 0.0  # 估算涨跌幅（%）
    nav_date: str = ""            # 最近净值日期
    estimate_time: str = ""       # 估算时间

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class PremiumDiscount:
    """溢价率/折价率计算结果。"""
    fund_code: str
    fund_name: str
    intraday_price: float       # 场内实时价格
    estimated_nav: float        # 估算净值
    premium_pct: float = 0.0    # 溢价率 = (价格-净值)/净值 * 100
    signal: str = ""            # 套利信号: "折价买入" / "溢价卖出" / "无明显机会"

    def to_dict(self) -> dict:
        return asdict(self)


# ====================================================================
# 腾讯行情解析（字段索引见上方注释）
# ====================================================================

# 腾讯返回格式:
# v_sz160223="51~基金名~代码~现价~昨收~今开~成交量~成交额~...~时间戳~涨跌额~涨跌幅~最高~最低~现价/成交量/成交额~..."
# 关键字段:
#   [3]  现价 (price)
#   [4]  昨收 (prev_close)
#   [5]  今开 (open_)
#   [33] 最高 (high)
#   [34] 最低 (low)
#   [6]  成交量 (volume, 手)
#   [7]  成交额 (amount, 元)
#   [31] 涨跌额
#   [32] 涨跌幅 (%)
#   [30] 时间戳 YYYYMMDDHHMMSS

_TENCENT_RE = re.compile(r'v_(?P<code>\w+)="(?P<body>[^"]*)";')


def _parse_tencent(code: str, body: str) -> Optional[IntradayQuote]:
    """解析腾讯实时行情一行。"""
    parts = body.split("~")
    if len(parts) < 35:
        return None
    try:
        price = float(parts[3] or 0)
        prev_close = float(parts[4] or 0)
        open_ = float(parts[5] or 0)
        high = float(parts[33] or 0)
        low = float(parts[34] or 0)
        volume = int(float(parts[6] or 0))  # 手
        amount = float(parts[7] or 0)       # 元 (实际可能是万元, 需确认)
        change_pct = float(parts[32] or 0)
        ts = parts[30] if len(parts) > 30 else ""
        date_str, time_str = "", ""
        if ts and len(ts) >= 14:
            date_str = f"{ts[0:4]}-{ts[4:6]}-{ts[6:8]}"
            time_str = f"{ts[8:10]}:{ts[10:12]}:{ts[12:14]}"

        name = parts[1] if len(parts) > 1 else ""
        # 提取纯代码 (去掉 sh/sz/bj 前缀)
        pure_code = code[2:] if code[:2] in ("sh", "sz", "bj") else code

        return IntradayQuote(
            fund_code=pure_code,
            fund_name=name,
            price=price,
            prev_close=prev_close,
            open_=open_,
            high=high,
            low=low,
            volume=volume,
            amount=amount,
            change_pct=change_pct,
            date=date_str,
            time=time_str,
        )
    except (ValueError, IndexError):
        return None


# ====================================================================
# Lazy imports for fund_estimator_index_agent (fallback when fundgz is down)
# ====================================================================

_estimate_realtime_fn = None


def _ensure_imports():
    """延迟导入 fund_estimator_index_agent，避免循环导入。"""
    global _estimate_realtime_fn
    if _estimate_realtime_fn is not None:
        return
    try:
        # __file__ is: .../fund_estimator/data_sources/fund_realtime.py
        _realpath = os.path.realpath(__file__)
        _data_sources_dir = os.path.dirname(_realpath)
        _fund_estimator_dir = os.path.dirname(_data_sources_dir)
        _code_root = os.path.dirname(_fund_estimator_dir)
        _code_root_abs = os.path.abspath(_code_root)
        if _code_root_abs not in sys.path:
            sys.path.insert(0, _code_root_abs)
        from fund_estimator.fund_estimator_index_agent import estimate_realtime
        _estimate_realtime_fn = estimate_realtime
    except Exception:
        # 静默失败，不影响主流程
        _estimate_realtime_fn = None


def _call_estimate_realtime(fund_code: str, date: str):
    """调用估值引擎，失败返回 None。"""
    if _estimate_realtime_fn is None:
        _ensure_imports()
    if _estimate_realtime_fn is None:
        return None
    try:
        return _estimate_realtime_fn(fund_code, date)
    except Exception:
        return None

_TIAN_TIAN_RE = re.compile(
    r'jsonpgz\(\s*\{([^}]+)\}\s*\)', re.DOTALL
)


def _parse_tiantian(code: str, text: str) -> Optional[FundEstimate]:
    """解析天天基金 fundgz 返回的 JSONP。"""
    m = _TIAN_TIAN_RE.search(text)
    if not m:
        return None
    try:
        import json
        obj = json.loads("{" + m.group(1) + "}")
        pure_code = code[2:] if code[:2] in ("sh", "sz", "bj") else code
        return FundEstimate(
            fund_code=pure_code,
            fund_name=obj.get("name", ""),
            estimated_nav=float(obj.get("gsz", 0)),
            estimated_change_pct=float(obj.get("gszzl", 0)),
            nav_date=obj.get("jzrq", ""),
            estimate_time=obj.get("gztime", ""),
        )
    except (json.JSONDecodeError, ValueError):
        return None


# ====================================================================
# 主获取函数
# ====================================================================

def _build_tencent_code(fund_code: str) -> str:
    """将 6 位基金代码转为腾讯行情代码。
    
    基金代码规则:
    - 15xxxx (深交所场内基金) -> sz15xxxx
    - 16xxxx, 17xxxx, 18xxxx, 19xxxx (LOF/ETF) -> sz16xxxx 等
    - 其他 -> 默认 sz
    
    注意: 部分沪市基金代码如 501018 -> sh501018
    """
    fc = fund_code.strip()
    if not fc or len(fc) != 6:
        return ""
    
    # 沪市基金: 5 开头, 或 1 开头但非深市范围
    if fc[0] == '5':
        return f"sh{fc}"
    # 大部分 LOF 在深交所: 16, 15, 17, 18, 19 开头
    elif fc[0] in ('1', '0'):
        return f"sz{fc}"
    else:
        return f"sz{fc}"


def fetch_intraday_quote(fund_code: str) -> Optional[IntradayQuote]:
    """获取单只基金的场内实时行情。"""
    tencent_code = _build_tencent_code(fund_code)
    if not tencent_code:
        return None
    
    url = f"http://qt.gtimg.cn/q={tencent_code}"
    try:
        text = http_get(url, encoding="gbk")
        m = _TENCENT_RE.search(text)
        if m:
            return _parse_tencent(m.group("code"), m.group("body"))
    except Exception:
        pass
    return None


def fetch_intraday_quotes_batch(codes: list[str]) -> Dict[str, IntradayQuote]:
    """批量获取场内实时行情。"""
    tencent_codes = [_build_tencent_code(c) for c in codes]
    tencent_codes = [c for c in tencent_codes if c]
    
    if not tencent_codes:
        return {}
    
    url = f"http://qt.gtimg.cn/q={','.join(tencent_codes)}"
    out: Dict[str, IntradayQuote] = {}
    try:
        text = http_get(url, encoding="gbk")
        for m in _TENCENT_RE.finditer(text):
            quote = _parse_tencent(m.group("code"), m.group("body"))
            if quote:
                out[quote.fund_code] = quote
    except Exception:
        pass
    return out


def fetch_estimate(fund_code: str) -> Optional[FundEstimate]:
    """获取基金的估算净值。

    数据源优先级:
    1. 天天基金 fundgz 接口（2026年1月30日起已下线）
    2. fund_estimator_index_agent 估值引擎（fallback）
    """
    import datetime

    # --- Primary: 天天基金 fundgz (已下线，保留备用) ---
    url = f"http://fundgz.1234567.com.cn/js/{fund_code}.js"
    try:
        text = http_get(url, encoding="utf-8")
        result = _parse_tiantian(fund_code, text)
        if result and result.estimated_nav > 0:
            return result
    except Exception:
        pass

    # --- Fallback: 使用 fund_estimator_index_agent 估值 ---
    try:
        est_result = _call_estimate_realtime(fund_code, datetime.datetime.now().strftime("%Y-%m-%d"))
        if est_result and est_result.get("success"):
            est_nav = est_result.get("estimated_nav", 0)
            est_change = est_result.get("estimated_change_pct", 0)
            if est_nav > 0:
                fund_name = ""
                fund_info = est_result.get("fund_info", {})
                if fund_info.get("fund_name"):
                    fund_name = fund_info["fund_name"]
                elif fund_info.get("tracker_index"):
                    fund_name = fund_info["tracker_index"]
                return FundEstimate(
                    fund_code=fund_code,
                    fund_name=fund_name,
                    estimated_nav=est_nav,
                    estimated_change_pct=round(est_change, 2),
                    nav_date=est_result.get("trade_date", ""),
                    estimate_time=datetime.datetime.now().strftime("%H:%M:%S"),
                )
    except Exception:
        pass

    return None


def fetch_estimate_batch(codes: list[str]) -> Dict[str, FundEstimate]:
    """批量获取估算净值（逐只请求，避免 URL 过长）。"""
    out: Dict[str, FundEstimate] = {}
    for code in codes:
        est = fetch_estimate(code)
        if est:
            out[code] = est
        time.sleep(0.1)  # 限流
    return out


def calculate_premium_discount(
    fund_code: str,
    intraday: IntradayQuote,
    estimate: FundEstimate,
) -> PremiumDiscount:
    """计算溢价率/折价率，给出套利信号。"""
    price = intraday.price
    nav = estimate.estimated_nav
    
    if nav <= 0 or price <= 0:
        return PremiumDiscount(
            fund_code=fund_code,
            fund_name=intraday.fund_name or estimate.fund_name,
            intraday_price=price,
            estimated_nav=nav,
            signal="数据不足",
        )
    
    premium_pct = (price - nav) / nav * 100.0
    
    # 套利信号判断
    if premium_pct > 1.0:
        signal = "溢价卖出(申购转场内)"
    elif premium_pct < -1.0:
        signal = "折价买入(转场内赎回)"
    else:
        signal = "无明显机会"
    
    return PremiumDiscount(
        fund_code=fund_code,
        fund_name=intraday.fund_name or estimate.fund_name,
        intraday_price=round(price, 4),
        estimated_nav=round(nav, 4),
        premium_pct=round(premium_pct, 2),
        signal=signal,
    )


def fetch_fund_snapshot(fund_code: str) -> Optional[dict]:
    """获取单只基金的综合快照（场内价格 + 估算净值 + 溢价率）。"""
    intraday = fetch_intraday_quote(fund_code)
    estimate = fetch_estimate(fund_code)
    
    if not intraday or not estimate:
        return {
            "fund_code": fund_code,
            "fund_name": intraday.fund_name if intraday else estimate.fund_name,
            "error": "数据不全",
            "intraday_price": 0,
            "estimated_nav": 0,
            "premium_pct": 0,
            "signal": "数据不足",
        }
    
    pd_result = calculate_premium_discount(fund_code, intraday, estimate)
    
    return {
        "fund_code": pd_result.fund_code,
        "fund_name": pd_result.fund_name,
        "intraday_price": pd_result.intraday_price,
        "estimated_nav": pd_result.estimated_nav,
        "premium_pct": pd_result.premium_pct,
        "signal": pd_result.signal,
        "intraday_change_pct": intraday.change_pct,
        "estimate_change_pct": estimate.estimated_change_pct,
        "intraday_time": intraday.time,
        "estimate_time": estimate.estimate_time,
    }


def fetch_all_fund_snapshots(fund_codes: list[str]) -> list[dict]:
    """批量获取多只基金的综合快照。"""
    # 先批量获取场内价格
    intraday_map = fetch_intraday_quotes_batch(fund_codes)
    # 再逐只获取估算净值
    estimate_map = fetch_estimate_batch(fund_codes)
    
    results = []
    for code in fund_codes:
        intraday = intraday_map.get(code)
        estimate = estimate_map.get(code)
        
        if not intraday or not estimate:
            results.append({
                "fund_code": code,
                "fund_name": intraday.fund_name if intraday else estimate.fund_name if estimate else code,
                "intraday_price": 0,
                "estimated_nav": 0,
                "premium_pct": 0,
                "signal": "数据不足",
                "error": "intraday" if not intraday else "estimate",
            })
            continue
        
        pd_result = calculate_premium_discount(code, intraday, estimate)
        results.append({
            "fund_code": pd_result.fund_code,
            "fund_name": pd_result.fund_name,
            "intraday_price": pd_result.intraday_price,
            "estimated_nav": pd_result.estimated_nav,
            "premium_pct": pd_result.premium_pct,
            "signal": pd_result.signal,
            "intraday_change_pct": intraday.change_pct,
            "estimate_change_pct": estimate.estimated_change_pct,
            "intraday_time": intraday.time,
            "estimate_time": estimate.estimate_time,
        })
    
    return results


if __name__ == "__main__":
    # 测试: 160223 国泰创业板LOF
    snapshot = fetch_fund_snapshot("160223")
    print("单只基金快照:")
    print(f"  基金: {snapshot['fund_name']} ({snapshot['fund_code']})")
    print(f"  场内价格: {snapshot['intraday_price']}")
    print(f"  估算净值: {snapshot['estimated_nav']}")
    print(f"  溢价率: {snapshot['premium_pct']}%")
    print(f"  信号: {snapshot['signal']}")
    print(f"  场内时间: {snapshot.get('intraday_time', '')}")
    print(f"  估算时间: {snapshot.get('estimate_time', '')}")
