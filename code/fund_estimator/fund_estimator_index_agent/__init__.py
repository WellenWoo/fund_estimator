"""fund_estimator_index_agent — 被动指数型基金实时估值 Agent

通用化的被动指数型基金实时估值引擎。用户只需输入任意基金代码（如 160223、
159915、510300 等），Agent 自动完成以下流程：

    1. 查询基金基本信息（名称、类型、跟踪指数）
    2. 判断是否为被动指数型（指数型 / LOF / ETF）
    3. 选择估值算法：
       - 被动指数型 → 参考指数法 (v_index_full_no_cash)
       - 主动管理型 → 持仓还原法 (v_top10 / v_index_blend)
    4. 执行估值并输出结果

设计原则：
- 复用 fund_estimator 现有模块（models, data_sources, estimators, backtest）
- 不引入任何第三方依赖（仅标准库 urllib + re + json + dataclasses + argparse）
- 支持 CLI 交互模式和单次运行模式

用法::

    # 单次估值（盘中）
    python -m fund_estimator_index_agent --fund 160223 --date 2026-07-16

    # 交互式模式
    python -m fund_estimator_index_agent --interactive

    # 批量估值
    python -m fund_estimator_index_agent --fund 160223 --batch --start 2026-07-01 --end 2026-07-16
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional

# ---------------------------------------------------------------------------
# Ensure project root is on sys.path
# ---------------------------------------------------------------------------
_THIS = os.path.dirname(os.path.abspath(__file__))
_CODE_ROOT = os.path.dirname(os.path.dirname(_THIS))  # code/
if _CODE_ROOT not in sys.path:
    sys.path.insert(0, _CODE_ROOT)

from fund_estimator.core.models import (  # noqa: E402
    FundHolding,
    RealtimeQuote,
    NAVEstimate,
    NAVComparison,
    THRESHOLD_PP,
    _guess_market,
)
from fund_estimator.data_sources.cache import CsvCache, http_get, cache_dir  # noqa: E402
from fund_estimator.data_sources.eastmoney.nav_history import fetch_nav_history  # noqa: E402
from fund_estimator.data_sources.eastmoney.holding import fetch_top10_holdings  # noqa: E402
from fund_estimator.data_sources.eastmoney.holdings_full import fetch_full_holdings  # noqa: E402
from fund_estimator.data_sources.sina.realtime import fetch_realtime as fetch_realtime_sina  # noqa: E402
from fund_estimator.data_sources.sina.history import fetch_kline  # noqa: E402
from fund_estimator.data_sources.tencent.realtime import fetch_realtime as fetch_realtime_tencent  # noqa: E402
from fund_estimator.data_sources.tiantian import fetch_official_estimate  # noqa: E402
from fund_estimator.estimators.holdings_based import (  # noqa: E402
    estimate as estimate_nav,
    METHODS,
    METHOD_LABELS,
    DEFAULT_METHOD,
    CYB_INDEX,
)
from fund_estimator.backtest.run_backtest import (  # noqa: E402
    load_common_inputs,
    backtest_range,
    _prev_trading_day,
    _quotes_from_close,
    estimate_for_day,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# 天天基金全量基金代码列表（用于基金信息查询）
FUND_LIST_URL = "http://fund.eastmoney.com/js/fundcode_search.js"

# 天天基金官方盘中估值接口（fundgz）
FUND_GZ_URL = "http://fundgz.1234567.com.cn/js/{code}.js"

# 东方财富基金档案页面（获取基金名称等基本信息）
FUND_INFO_URL = "http://fund.eastmoney.com/pingzhongdata/{code}.js"

# 正则表达式
_FUND_CODE_RE = re.compile(r"^\d{6}$")

# 指数代码映射（常见指数名称关键词 → (symbol_code, exchange_prefix)）
INDEX_SYMBOL_MAP = {
    "沪深300": ("000300", "sh"),
    "沪深300指数": ("000300", "sh"),
    "中证500": ("000905", "sh"),
    "中证500指数": ("000905", "sh"),
    "上证50": ("000016", "sh"),
    "上证50指数": ("000016", "sh"),
    "创业板指": ("399006", "sz"),
    "创业板指数": ("399006", "sz"),
    "创业板": ("399006", "sz"),
    "科创50": ("000688", "sh"),
    "科创50指数": ("000688", "sh"),
    "上证180": ("000010", "sh"),
    "上证180指数": ("000010", "sh"),
    "深证100": ("399004", "sz"),
    "深证100指数": ("399004", "sz"),
    "中小板指": ("399005", "sz"),
    "中小板指数": ("399005", "sz"),
    "中证1000": ("000852", "sh"),
    "中证1000指数": ("000852", "sh"),
    "国证2000": ("399303", "sz"),
    "国证2000指数": ("399303", "sz"),
    "上证综指": ("000001", "sh"),
    "上证指数": ("000001", "sh"),
    "深证成指": ("399001", "sz"),
    "深证成分指数": ("399001", "sz"),
    "恒生指数": ("hs_hsi", "hk"),
    "纳斯达克": ("ndx", "us"),
    "标普500": ("spx", "us"),
    "纳斯达克100": ("ndx", "us"),
    "中证红利": ("000922", "sh"),
    "中证红利指数": ("000922", "sh"),
    "中证消费": ("000031", "sh"),
    "中证医药": ("000932", "sh"),
    "中证银行": ("000827", "sh"),
    "中证能源": ("000933", "sh"),
    "中证军工": ("000998", "sh"),
    "中证新能源": ("399808", "sz"),
    "中证环保": ("000723", "sh"),
    "中证农业": ("000169", "sh"),
    "中证电子": ("000714", "sh"),
    "中证汽车": ("000801", "sh"),
    "中证白酒": ("000812", "sh"),
    "中证食品饮料": ("000807", "sh"),
    "中证光伏": ("000826", "sh"),
    "中证煤炭": ("000955", "sh"),
    "中证通信": ("000738", "sh"),
    "中证计算机": ("000928", "sh"),
    "中证传媒": ("000819", "sh"),
    "中证半导体": ("000937", "sh"),
    "中证人工智能": ("000828", "sh"),
    "中证新能源汽车": ("930725", "cn"),
    "中证5G": ("930905", "cn"),
    "中证医疗": ("000809", "sh"),
    "中证电力": ("000958", "sh"),
    "中证全指医药": ("000999", "sh"),
    "中证TMT": ("000825", "sh"),
    "中证非银金融": ("000828", "sh"),
    "中证证券保险": ("000828", "sh"),
    "中证有色金属": ("000935", "sh"),
    "中证化工": ("000952", "sh"),
    "中证家电": ("000831", "sh"),
    "中证旅游": ("000811", "sh"),
    "中证影视": ("000830", "sh"),
    "中证国防": ("000822", "sh"),
    "中证畜牧养殖": ("000960", "sh"),
}

# 基金类型关键词（用于判断是否为被动指数型）
_PASSIVE_KEYWORDS = [
    "指数型", "指数", "LOF", "ETF", "指数增强",
    "指数(lof)", "指数型(LOF)", "指数型(ETF)",
    "指数型（LOF）", "指数型（ETF）",
    "被动指数", "被动型指数",
]

# ---------------------------------------------------------------------------
# Data Classes
# ---------------------------------------------------------------------------

@dataclass
class FundInfo:
    """基金基本信息。"""
    fund_code: str
    fund_name: str = ""
    fund_type: str = ""  # 股票型、混合型、指数型、债券型、QDII、货币...
    fund_subtype: str = ""  # 被动指数、指数增强、LOF、ETF...
    manager: str = ""  # 基金管理人
    tracker_index: str = ""  # 跟踪指数名称
    tracker_index_code: str = ""  # 跟踪指数代码（如 399006）
    is_passive: bool = False  # 是否为被动指数型基金
    nav_history: list[dict] = field(default_factory=list)  # 历史净值
    holdings: list[FundHolding] = field(default_factory=list)  # 最新持仓

    def to_dict(self) -> dict:
        return {
            "fund_code": self.fund_code,
            "fund_name": self.fund_name,
            "fund_type": self.fund_type,
            "fund_subtype": self.fund_subtype,
            "manager": self.manager,
            "tracker_index": self.tracker_index,
            "tracker_index_code": self.tracker_index_code,
            "is_passive": self.is_passive,
        }


# ---------------------------------------------------------------------------
# 1. Fund Information Query
# ---------------------------------------------------------------------------

def fetch_fund_list() -> list[dict]:
    """从天天基金获取全市场基金代码列表。

    Returns
    -------
    list[dict]
        每项含 {"fundcode", "fundname", "type"}。
    """
    try:
        text = http_get(FUND_LIST_URL, encoding="utf-8")
    except RuntimeError:
        return []

    # Find 'var r = [' and match balanced brackets to extract the full array
    m = re.search(r'var\s+r\s*=\s*\[', text)
    if not m:
        return []
    start = m.end() - 1  # position of '['
    depth = 0
    end = start
    for i in range(start, len(text)):
        if text[i] == '[':
            depth += 1
        elif text[i] == ']':
            depth -= 1
            if depth == 0:
                end = i
                break

    array_text = text[start:end + 1]
    try:
        data = json.loads(array_text)
    except json.JSONDecodeError:
        return []

    results = []
    for item in data:
        if isinstance(item, (list, tuple)) and len(item) >= 4:
            # Format: [code, pinyin, name, type, full_name, ...]
            results.append({
                "fundcode": str(item[0]),
                "fundname": str(item[2]),
                "type": str(item[3]),
            })
        elif isinstance(item, dict):
            # Old format: {db:..., mc:...}
            results.append({
                "fundcode": str(item.get("db", item.get("fundcode", ""))),
                "fundname": str(item.get("mc", item.get("fundname", ""))),
                "type": str(item.get("type", "")),
            })

    return results

    return results


# Global fund list cache (lazy-loaded)
_fund_list_cache: Optional[dict[str, dict]] = None


def get_fund_list_cache() -> dict[str, dict]:
    """获取基金列表缓存，首次调用时自动加载。"""
    global _fund_list_cache
    if _fund_list_cache is None:
        _fund_list_cache = {}
        items = fetch_fund_list()
        for item in items:
            _fund_list_cache[item["fundcode"]] = item
    return _fund_list_cache


def query_fund_basic_info(fund_code: str) -> dict:
    """查询基金基本信息（名称、类型等）从天天基金 fundgz 接口。

    Returns
    -------
    dict with keys: fundcode, fundname, fundtype, manager, ...
    """
    info = {}
    try:
        url = FUND_GZ_URL.format(code=fund_code)
        text = http_get(url, encoding="utf-8", referer="http://fund.eastmoney.com/")
        m = re.search(r'jsonpgz\((?P<json>\{.*\})\)\s*;', text, re.S)
        if m:
            data = json.loads(m.group("json"))
            info["fundcode"] = data.get("fundcode", fund_code)
            info["fundname"] = data.get("name", "")
            info["fundtype"] = data.get("fundtype", "")
            info["manager"] = data.get("manager", "")
    except RuntimeError:
        pass
    return info


def query_fund_detail(fund_code: str) -> dict:
    """查询基金详细信息（跟踪指数、基金类型子类等）。

    从东方财富 pingzhongdata 页面提取结构化信息。
    注意：JS 变量名可能随东方财富改版而变化，此处做多重兼容。
    """
    info = {}
    try:
        url = FUND_INFO_URL.format(code=fund_code)
        text = http_get(url, encoding="utf-8", referer="http://fund.eastmoney.com/")

        # Helper: extract JS variable value (handles both quoted and unquoted)
        def _extract(var_name: str) -> Optional[str]:
            # Try double-quoted
            m = re.search(rf'var\s+{var_name}\s*=\s*"([^"]*)"', text)
            if m:
                return m.group(1).strip()
            # Try single-quoted
            m = re.search(rf"var\s+{var_name}\s*=\s*'([^']*)'", text)
            if m:
                return m.group(1).strip()
            # Try unquoted
            m = re.search(rf'var\s+{var_name}\s*=\s*([^\s;"\n]+)', text)
            return m.group(1).strip() if m else None

        info["fundtype"] = _extract("fundtype") or ""
        info["fundsubtype"] = _extract("fundsubtype") or ""
        info["manager"] = _extract("jjgm") or ""
        info["tracker_index"] = _extract("indexname") or ""
        info["tracker_index_code"] = _extract("indexcode") or ""
        info["fundcode"] = _extract("fundcode") or fund_code
        info["fundname"] = _extract("fundname") or ""
        info["fundfullname"] = _extract("fundfullname") or ""

        # 兼容新版东方财富 pingzhongdata 变量名
        if not info["fundname"]:
            info["fundname"] = _extract("fS_name") or ""
        if not info["fundcode"]:
            info["fundcode"] = _extract("fS_code") or fund_code

    except RuntimeError:
        pass

    return info


def classify_fund_type(fund_code: str) -> FundInfo:
    """综合判断基金类型，返回 FundInfo 对象。

    流程：
    1. 从天天基金 fundgz 接口获取基本信息（名称最可靠）
    2. 从东方财富 pingzhongdata 获取详细信息
    3. 判断是否为被动指数型基金
    4. 从基金代码列表获取补充信息

    Returns
    -------
    FundInfo
    """
    info = FundInfo(fund_code=fund_code)

    # Step 1: 天天基金 fundgz（最可靠的基金名称来源）
    basic = query_fund_basic_info(fund_code)
    if basic.get("fundname"):
        info.fund_name = basic["fundname"]
    if basic.get("fundtype"):
        info.fund_type = basic["fundtype"]
    if basic.get("manager"):
        info.manager = basic["manager"]

    # Step 2: 东方财富 pingzhongdata（兼容新旧格式）
    detail = query_fund_detail(fund_code)
    if detail.get("fundname") and not info.fund_name:
        info.fund_name = detail["fundname"]
    if detail.get("fundfullname") and not info.fund_name:
        info.fund_name = detail["fundfullname"]
    if detail.get("fundtype") and not info.fund_type:
        info.fund_type = detail["fundtype"]
    if detail.get("fundsubtype"):
        info.fund_subtype = detail["fundsubtype"]
    if detail.get("manager") and not info.manager:
        info.manager = detail["manager"]
    if detail.get("tracker_index") and not info.tracker_index:
        info.tracker_index = detail["tracker_index"]
    if detail.get("tracker_index_code") and not info.tracker_index_code:
        info.tracker_index_code = detail["tracker_index_code"]

    # Step 3: 基金代码列表
    flist = get_fund_list_cache()
    if fund_code in flist:
        fi = flist[fund_code]
        if not info.fund_name:
            info.fund_name = fi.get("fundname", "")
        if not info.fund_type:
            info.fund_type = fi.get("type", "")

    # Step 4: 判断是否为被动指数型基金
    info.is_passive = _is_passive_index_fund(info)

    return info


def _is_passive_index_fund(info: FundInfo) -> bool:
    """判断基金是否为被动指数型。

    判断规则（综合多个信号）：
    1. fund_name 包含"指数"和"LOF/ETF"（最强信号）
    2. fund_type 包含"指数型"
    3. fund_subtype 包含"指数"、"LOF"、"ETF"
    4. tracker_index 非空
    5. 基金代码列表中的 type 字段

    至少有 2 个信号认为是被动指数型。
    """
    signals = 0

    # Signal 1: fund_name 包含"指数"（强信号，权重 2）
    if info.fund_name:
        if "指数" in info.fund_name:
            signals += 2
            # 如果还包含 LOF/ETF，额外加分
            if "LOF" in info.fund_name or "ETF" in info.fund_name or "lof" in info.fund_name or "etf" in info.fund_name:
                signals += 1

    # Signal 2: fund_type 包含指数型关键词
    if info.fund_type:
        for kw in _PASSIVE_KEYWORDS:
            if kw in info.fund_type:
                signals += 1
                break

    # Signal 3: fund_subtype 包含指数/LOF/ETF
    if info.fund_subtype:
        for kw in ["指数", "LOF", "ETF", "lof", "etf"]:
            if kw in info.fund_subtype:
                signals += 1
                break

    # Signal 4: 有跟踪指数（高权重）
    if info.tracker_index and info.tracker_index != "未知指数":
        signals += 2

    # Signal 5: 基金代码列表中的 type 字段
    flist = get_fund_list_cache()
    if info.fund_code in flist:
        ft = flist[info.fund_code].get("type", "").lower()
        if "index" in ft or "指数" in ft:
            signals += 1

    # 至少有 2 个信号认为是被动指数型
    return signals >= 2


def resolve_index_symbol(tracker_index: str, tracker_index_code: str) -> Optional[str]:
    """将跟踪指数名称或代码解析为实时行情可用的 symbol。

    Parameters
    ----------
    tracker_index: 指数名称，如 "创业板指"
    tracker_index_code: 指数代码，如 "399006"

    Returns
    -------
    str or None
        标准化 symbol，如 "sz399006"。
    """
    # 优先使用 tracker_index_code
    if tracker_index_code:
        code = tracker_index_code
        # 检查是否在 INDEX_SYMBOL_MAP 中
        for keyword, (sym_code, prefix) in INDEX_SYMBOL_MAP.items():
            if keyword in code or code in keyword:
                return f"{prefix}{sym_code}"

        # 尝试直接从代码推断交易所
        if len(code) == 6:
            if code.startswith("399"):
                return f"sz{code}"
            if code.startswith("000") and not code.startswith("0008"):
                return f"sh{code}"
            if code.startswith("930"):
                return f"cn{code}"
            return f"sh{code}"

    # 尝试从名称匹配
    if tracker_index:
        for keyword, (sym_code, prefix) in INDEX_SYMBOL_MAP.items():
            if keyword in tracker_index:
                return f"{prefix}{sym_code}"

    # 最后尝试：如果是常见指数代码格式，直接拼接
    if tracker_index_code and len(tracker_index_code) == 6:
        code = tracker_index_code
        if code.startswith("399"):
            return f"sz{code}"
        if code.startswith("000"):
            return f"sh{code}"

    return None


# ---------------------------------------------------------------------------
# 2. Smart Algorithm Selection
# ---------------------------------------------------------------------------

def select_estimation_method(fund_info: FundInfo) -> tuple[str, str]:
    """根据基金类型选择最优估值算法。

    Parameters
    ----------
    fund_info: 基金基本信息

    Returns
    -------
    (method, reason)
        method: 算法标识
        reason: 选择理由
    """
    if fund_info.is_passive:
        return (
            "v_index_full_no_cash",
            (f"被动指数型基金（{fund_info.fund_name}），"
             f"跟踪{fund_info.tracker_index}，"
             f"采用参考指数法 v_index_full_no_cash（MAE 0.11pp，最优算法）"),
        )
    else:
        # 主动管理型基金 → 持仓还原法
        if fund_info.holdings:
            covered = sum(h.weight_pct for h in fund_info.holdings)
            if covered > 70:
                return (
                    "v_index_blend",
                    (f"主动管理型基金（{fund_info.fund_name}），"
                     f"前十大持仓覆盖 {covered:.1f}%，"
                     f"采用混合算法 v_index_blend"),
                )
            else:
                return (
                    "v_top10",
                    (f"主动管理型基金（{fund_info.fund_name}），"
                     f"前十大持仓覆盖 {covered:.1f}%，"
                     f"采用持仓还原法 v_top10"),
                )
        else:
            return (
                "v_top10",
                (f"主动管理型基金（{fund_info.fund_name}），"
                 f"无持仓数据，默认采用持仓还原法 v_top10"),
            )


# ---------------------------------------------------------------------------
# 3. Real-time Estimation Engine
# ---------------------------------------------------------------------------

def estimate_realtime(
    fund_code: str,
    trade_date: str,
    method: Optional[str] = None,
    force: bool = False,
) -> dict:
    """执行实时估值计算。

    Parameters
    ----------
    fund_code: 基金代码（6 位数字）
    trade_date: 估值目标日期（YYYY-MM-DD）
    method: 指定算法（可选，None 则自动选择）
    force: 是否强制重新抓取数据

    Returns
    -------
    dict: 估值结果
    """
    cache = CsvCache()

    # Step 1: 查询基金信息
    fund_info = classify_fund_type(fund_code)

    # Step 2: 获取持仓数据
    try:
        full_holdings = fetch_full_holdings(fund_code, cache=cache, force=force)
        fund_info.holdings = full_holdings.holdings
    except RuntimeError:
        pass

    # Step 3: 选择算法
    if method is None:
        method, reason = select_estimation_method(fund_info)
    else:
        reason = f"用户指定算法: {method}"

    # Step 4: 执行估值
    # 需要向前扩展日期范围以确保 T-1 数据可用
    # 扩展 30 天以覆盖周末和非交易日
    try:
        trade_dt = datetime.strptime(trade_date, "%Y-%m-%d")
        start_date = (trade_dt - timedelta(days=30)).strftime("%Y-%m-%d")
    except ValueError:
        start_date = ""

    try:
        need_stocks = method in ("v_top10", "v_index_blend", "v_residual_uncovered")
        inputs = load_common_inputs(
            fund_code, start_date, trade_date,
            with_holdings=True, with_stocks=need_stocks,
            cache=cache, force=force,
        )
        comp = estimate_for_day(inputs, trade_date, method)

        if comp is None:
            return {
                "success": False,
                "fund_code": fund_code,
                "trade_date": trade_date,
                "error": f"{trade_date} 非交易日或数据缺失，无法估值",
                "fund_info": fund_info.to_dict(),
                "method_used": method,
                "method_reason": reason,
            }

        est = comp.estimate
        result = {
            "success": True,
            "fund_code": fund_code,
            "trade_date": trade_date,
            "t1_date": est.t1_date,
            "t1_nav": est.t1_nav,
            "estimated_nav": est.estimated_nav,
            "estimated_change_pct": est.estimated_change_pct,
            "method": est.method,
            "method_reason": reason,
            "fund_info": fund_info.to_dict(),
            "detail": est.detail,
        }

        if comp.official_nav is not None:
            result["official_nav"] = comp.official_nav
            result["official_change_pct"] = (
                round(comp.official_change_pct, 4) if comp.official_change_pct is not None else None
            )
            result["abs_error"] = round(comp.abs_error, 6) if comp.abs_error is not None else None
            result["error_pp"] = round(comp.error_pp, 4) if comp.error_pp is not None else None
            result["over_threshold"] = comp.over_threshold

        return result

    except Exception as e:
        return {
            "success": False,
            "fund_code": fund_code,
            "trade_date": trade_date,
            "error": str(e),
            "fund_info": fund_info.to_dict(),
            "method_used": method,
            "method_reason": reason,
        }


def estimate_batch(
    fund_code: str,
    start_date: str,
    end_date: str,
    method: Optional[str] = None,
    force: bool = False,
) -> list[dict]:
    """批量估值（多天）。"""
    results = []
    start = datetime.strptime(start_date, "%Y-%m-%d")
    end = datetime.strptime(end_date, "%Y-%m-%d")
    current = start

    while current <= end:
        date_str = current.strftime("%Y-%m-%d")
        res = estimate_realtime(fund_code, date_str, method=method, force=force)
        results.append(res)
        current += timedelta(days=1)

    return results


# ---------------------------------------------------------------------------
# 4. Output Formatting
# ---------------------------------------------------------------------------

def print_result(result: dict) -> None:
    """格式化输出估值结果。"""
    if not result.get("success"):
        print(f"\n[ERROR] Valuation failed: {result.get('error', 'Unknown error')}")
        return

    fund_info = result.get("fund_info", {})
    print("\n" + "=" * 60)
    print(f"  Fund Valuation Result -- {result['fund_code']}")
    print("=" * 60)

    # Fund Info
    print(f"\n  Fund Information")
    print(f"     Code:       {fund_info.get('fund_code', result['fund_code'])}")
    print(f"     Name:       {fund_info.get('fund_name', 'Unknown')}")
    passive_label = "[PASSIVE INDEX]" if fund_info.get("is_passive") else "[ACTIVE MANAGEMENT]"
    print(f"     Type:       {passive_label}")
    print(f"     Manager:    {fund_info.get('manager', 'Unknown')}")
    print(f"     Tracker:    {fund_info.get('tracker_index', 'Unknown')}")

    # Method
    print(f"\n  Estimation Method")
    print(f"     Algorithm:  {result['method']}")
    print(f"     Reason:     {result.get('method_reason', '')}")

    # Estimate
    print(f"\n  Estimate Result ({result['trade_date']})")
    print(f"     T-1 Date:   {result['t1_date']}")
    print(f"     T-1 NAV:    {result['t1_nav']:.4f}")
    print(f"     Est NAV:    {result['estimated_nav']:.4f}")
    print(f"     Est Change: {result['estimated_change_pct']:+.4f}%")

    # Official NAV comparison
    if "official_nav" in result:
        print(f"\n  Official Comparison")
        print(f"     Official NAV:     {result['official_nav']:.4f}")
        print(f"     Official Change:  {result['official_change_pct']:+.4f}%")
        print(f"     Abs Error:        {result.get('abs_error', 0):+.6f}")
        print(f"     Error (pp):       {result.get('error_pp', 0):+.4f} pp")
        threshold_str = "[OVER THRESHOLD]" if result.get("over_threshold") else "[PASS]"
        print(f"     Threshold ({THRESHOLD_PP}pp): {threshold_str}")
    else:
        print(f"\n  Official NAV not yet published (usually after 21:00)")


# ---------------------------------------------------------------------------
# 5. Interactive CLI
# ---------------------------------------------------------------------------

def interactive_mode() -> None:
    """交互式 CLI 模式。"""
    print("\n" + "=" * 60)
    print("  Passive Index Fund Estimator Agent")
    print("=" * 60)
    print("""
  Usage:
    1. Enter fund code (6 digits), e.g. 160223
    2. Enter valuation date (YYYY-MM-DD), leave blank for today
    3. Optionally specify method (e.g. v_index_full_no_cash)

  Hint: type 'quit' or 'q' to exit, 'help' for commands
""")

    # Pre-load fund list cache
    get_fund_list_cache()

    while True:
        try:
            fund_code = input("\nEnter fund code (6 digits): ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n\nGoodbye!")
            break

        if fund_code.lower() in ("quit", "q", "exit"):
            print("Goodbye!")
            break

        if fund_code.lower() == "help":
            print("""
  Available commands:
    quit / q       - Exit
    help           - Show this help
    list           - List common index funds
    info <code>    - Query fund basic info
    estimate <code> [date] [method] - Single estimation
    batch <code> <start> <end>      - Batch estimation
""")
            continue

        if fund_code.lower() == "list":
            print("\n  Common index funds:")
            common = ["160223", "159915", "510300", "510500", "510050",
                       "161725", "162711", "160706", "161810", "000311"]
            flist = get_fund_list_cache()
            for code in common:
                if code in flist:
                    fi = flist[code]
                    print(f"    {fi['fundcode']}: {fi['fundname']}")
                else:
                    print(f"    {code}: (not in cache)")
            continue

        if fund_code.lower() == "info":
            code = input("\nEnter fund code: ").strip()
            if code and _FUND_CODE_RE.match(code):
                info = classify_fund_type(code)
                print(f"\n  Fund Info:")
                print(f"    Code:        {info.fund_code}")
                print(f"    Name:        {info.fund_name}")
                print(f"    Type:        {info.fund_type} ({info.fund_subtype})")
                print(f"    Manager:     {info.manager}")
                print(f"    Tracker:     {info.tracker_index}")
                passive_label = "YES [PASSIVE]" if info.is_passive else "NO [ACTIVE]"
                print(f"    Passive:     {passive_label}")
            continue

        if fund_code.lower() == "estimate":
            code = input("\nEnter fund code: ").strip()
            date = input("Enter date (YYYY-MM-DD, blank=today): ").strip() or ""
            method = input("Enter method (blank=auto): ").strip() or None
            if not date:
                date = datetime.now().strftime("%Y-%m-%d")
            result = estimate_realtime(code, date, method=method)
            print_result(result)
            continue

        if fund_code.lower() == "batch":
            code = input("\nEnter fund code: ").strip()
            start = input("Start date (YYYY-MM-DD): ").strip()
            end = input("End date (YYYY-MM-DD): ").strip()
            if not start or not end:
                print("  Error: please provide start and end dates")
                continue
            results = estimate_batch(code, start, end)
            success_n = sum(1 for r in results if r.get("success"))
            fail_n = len(results) - success_n
            print(f"\n  Batch complete: {success_n} success, {fail_n} failed")
            for r in results:
                if r.get("success"):
                    est = r
                    off = ""
                    if "official_nav" in r:
                        off = f" | Official: {r['official_nav']:.4f} | Error: {r.get('error_pp', 0):+.4f}pp"
                    print(f"    {r['trade_date']}: Est NAV {est['estimated_nav']:.4f} "
                          f"(+/-{est['estimated_change_pct']:+.4f}%){off}")
            continue

        # Validate fund code format
        if not _FUND_CODE_RE.match(fund_code):
            print("  [ERROR] Invalid fund code format, please enter 6 digits")
            continue

        # Default valuation date
        date_input = input("Enter date (YYYY-MM-DD, blank=today): ").strip() or ""
        if not date_input:
            trade_date = datetime.now().strftime("%Y-%m-%d")
        else:
            trade_date = date_input

        method_input = input("Enter method (blank=auto): ").strip() or None

        print(f"\n  Querying fund {fund_code} info and estimating...")
        result = estimate_realtime(fund_code, trade_date, method=method_input)
        print_result(result)


def run_single(fund_code: str, trade_date: str, method: Optional[str] = None) -> int:
    """单次运行模式（CLI 入口）。"""
    if not _FUND_CODE_RE.match(fund_code):
        print(f"[ERROR] Invalid fund code: {fund_code} (need 6 digits)")
        return 1

    if not trade_date:
        trade_date = datetime.now().strftime("%Y-%m-%d")

    print(f"Querying fund {fund_code} info and estimating...")
    result = estimate_realtime(fund_code, trade_date, method=method)
    print_result(result)

    if result.get("success"):
        print("\n--- JSON ---")
        print(json.dumps(result, ensure_ascii=False, indent=2))

    return 0


# ---------------------------------------------------------------------------
# CLI Entry Point
# ---------------------------------------------------------------------------

def main(argv: Optional[list[str]] = None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

    parser = argparse.ArgumentParser(
        description="Passive Index Fund Real-time Estimation Agent",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Single estimation
  python -m fund_estimator_index_agent --fund 160223 --date 2026-07-16

  # Specify method
  python -m fund_estimator_index_agent --fund 160223 --date 2026-07-16 --method v_index_full_no_cash

  # Batch estimation
  python -m fund_estimator_index_agent --fund 160223 --batch --start 2026-07-01 --end 2026-07-16

  # Interactive mode
  python -m fund_estimator_index_agent --interactive
        """,
    )
    parser.add_argument("--fund", type=str, help="Fund code (6 digits)")
    parser.add_argument("--date", type=str, help="Valuation date (YYYY-MM-DD), default today")
    parser.add_argument("--method", type=str, default=None,
                        choices=METHODS,
                        help="Estimation method (optional, auto-select by default)")
    parser.add_argument("--interactive", action="store_true",
                        help="Interactive mode")
    parser.add_argument("--batch", action="store_true",
                        help="Batch estimation mode")
    parser.add_argument("--start", type=str, help="Batch start date (YYYY-MM-DD)")
    parser.add_argument("--end", type=str, help="Batch end date (YYYY-MM-DD)")
    parser.add_argument("--force", action="store_true",
                        help="Force refetch data (ignore cache)")
    parser.add_argument("--json", action="store_true",
                        help="Output only JSON format")

    args = parser.parse_args(argv)

    # Interactive mode
    if args.interactive:
        interactive_mode()
        return 0

    # Batch mode
    if args.batch:
        if not args.fund:
            print("[ERROR] Batch mode requires --fund parameter")
            return 1
        if not args.start or not args.end:
            print("[ERROR] Batch mode requires --start and --end parameters")
            return 1
        results = estimate_batch(args.fund, args.start, args.end,
                                 method=args.method, force=args.force)
        success_n = sum(1 for r in results if r.get("success"))
        fail_n = len(results) - success_n

        if args.json:
            print(json.dumps({
                "fund_code": args.fund,
                "start": args.start,
                "end": args.end,
                "total": len(results),
                "success": success_n,
                "failed": fail_n,
                "results": results,
            }, ensure_ascii=False, indent=2))
        else:
            print(f"\nBatch complete: {success_n} success, {fail_n} failed")
            for r in results:
                if r.get("success"):
                    est = r
                    off = ""
                    if "official_nav" in r:
                        off = f" | Official: {r['official_nav']:.4f} | Error: {r.get('error_pp', 0):+.4f}pp"
                    print(f"  {r['trade_date']}: Est NAV {est['estimated_nav']:.4f} "
                          f"(+/-{est['estimated_change_pct']:+.4f}%){off}")
        return 0

    # Single estimation mode
    if not args.fund:
        print("[ERROR] Please provide fund code (--fund) or use --interactive for interactive mode")
        return 1

    trade_date = args.date or datetime.now().strftime("%Y-%m-%d")
    return run_single(args.fund, trade_date, method=args.method)


if __name__ == "__main__":
    raise SystemExit(main())
