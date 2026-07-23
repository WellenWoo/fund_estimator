"""fund_estimator_index_agent — 被动指数型基金实时估值 Agent

通用化的被动指数型基金实时估值引擎。用户只需输入任意基金代码（如 160223、
159915、510300 等），Agent 自动完成以下流程：

    1. 读取本地数据库 master_lof 判断基金是被动型还是主动型
    2. 选择估值算法：
       - 被动指数型 → 参考指数法 (v_index_full_no_cash)
       - 主动管理型 → 持仓还原法 (v_top10 / v_index_blend)
    3. 执行估值并输出结果

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
import sqlite3
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

# Database path: lof_database/lof_info.db relative to project root
_DB_PATH = os.path.join(_CODE_ROOT, '..', 'lof_database', 'lof_info.db')

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

# 默认 fallback 指数：仅当基金不在数据库且无法判断时使用。
# 实际业务应由 classify_fund_type() 解析基金跟踪的指数后动态决定。
DEFAULT_FALLBACK_INDEX = "sz399006"

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

# 本地 SQLite 数据库路径
DB_PATH = _DB_PATH


def get_db_connection() -> sqlite3.Connection:
    """打开本地 lof_info.db 连接。如果数据库不存在则返回 None。"""
    if not os.path.exists(DB_PATH):
        return None
    try:
        conn = sqlite3.connect(DB_PATH, timeout=5)
        conn.row_factory = sqlite3.Row
        return conn
    except sqlite3.OperationalError:
        return None


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
# 1. Fund Information Query from local database
# ---------------------------------------------------------------------------

def fetch_fund_list() -> list[dict]:
    """从天天基金获取全市场基金代码列表。（保留以兼容外部调用）

    Returns
    -------
    list[dict]
        每项含 {"fundcode", "fundname", "type"}。
    """
    try:
        text = http_get(FUND_LIST_URL, encoding="utf-8")
    except RuntimeError:
        return []

    m = re.search(r'var\s+r\s*=\s*\[', text)
    if not m:
        return []
    start = m.end() - 1
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
            results.append({
                "fundcode": str(item[0]),
                "fundname": str(item[2]),
                "type": str(item[3]),
            })
        elif isinstance(item, dict):
            results.append({
                "fundcode": str(item.get("db", item.get("fundcode", ""))),
                "fundname": str(item.get("mc", item.get("fundname", ""))),
                "type": str(item.get("type", "")),
            })

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

    .. deprecated::
        已不再在实时估值链路中调用此函数。保留以兼容外部直接调用。

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

    .. deprecated::
        已不再在实时估值链路中调用此函数。保留以兼容外部直接调用。

    从东方财富 pingzhongdata 页面提取结构化信息。
    注意：JS 变量名可能随东方财富改版而变化，此处做多重兼容。
    """
    info = {}
    try:
        url = FUND_INFO_URL.format(code=fund_code)
        text = http_get(url, encoding="utf-8", referer="http://fund.eastmoney.com/")

        def _extract(var_name: str) -> Optional[str]:
            m = re.search(rf'var\s+{var_name}\s*=\s*"([^"]*)"', text)
            if m:
                return m.group(1).strip()
            m = re.search(rf"var\s+{var_name}\s*=\s*'([^']*)'", text)
            if m:
                return m.group(1).strip()
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

        if not info["fundname"]:
            info["fundname"] = _extract("fS_name") or ""
        if not info["fundcode"]:
            info["fundcode"] = _extract("fS_code") or fund_code

    except RuntimeError:
        pass

    return info


def query_db_fund_info(fund_code: str) -> Optional[FundInfo]:
    """从本地 SQLite 数据库 master_lof 表查询基金信息。

    返回 FundInfo 对象。若基金不在数据库中则返回 None。

    核心逻辑：
    - is_passive=1 表示该基金是被动指数型基金
    - tracker_index / tracker_index_code 为跟踪的指数名称和代码

    Parameters
    ----------
    fund_code : str
        6位基金代码

    Returns
    -------
    FundInfo or None
    """
    conn = get_db_connection()
    if conn is None:
        return None

    try:
        row = conn.execute(
            "SELECT fund_name, fund_type, tracker_index, tracker_index_code, is_passive "
            "FROM master_lof WHERE fund_code = ?",
            (fund_code,),
        ).fetchone()
    finally:
        conn.close()

    if row is None:
        return None

    info = FundInfo(fund_code=fund_code)
    info.fund_name = row["fund_name"] or ""
    info.fund_type = row["fund_type"] or ""
    info.tracker_index = row["tracker_index"] or ""
    info.tracker_index_code = row["tracker_index_code"] or ""
    info.is_passive = bool(row["is_passive"])
    return info


def classify_fund_type(fund_code: str) -> FundInfo:
    """综合判断基金类型，返回 FundInfo 对象。

    流程：
    1. **优先**从本地数据库 master_lof 表读取被动/主动型标识和跟踪指数（零网络请求）
    2. 若数据库中没有该基金，回退到联网查询：
       - 天天基金 fundgz 接口获取基金名称/类型
       - 东方财富 pingzhongdata 获取详细信息
       - 基金代码列表补充信息
    3. 最终判定是否被动指数型

    Returns
    -------
    FundInfo
    """
    info = FundInfo(fund_code=fund_code)

    # Step 1: 优先从本地数据库读取（零网络请求）
    db_info = query_db_fund_info(fund_code)
    if db_info is not None:
        info.fund_name = db_info.fund_name
        info.fund_type = db_info.fund_type
        info.tracker_index = db_info.tracker_index
        info.tracker_index_code = db_info.tracker_index_code
        info.is_passive = db_info.is_passive
        # 本地数据库已有完整且可靠的被动型标识，直接返回
        return info

    # Step 2: 数据库缺失时的回退方案（联网查询）

    # Step 2a: 天天基金 fundgz（最可靠的基金名称来源）
    basic = query_fund_basic_info(fund_code)
    if basic.get("fundname"):
        info.fund_name = basic["fundname"]
    if basic.get("fundtype"):
        info.fund_type = basic["fundtype"]
    if basic.get("manager"):
        info.manager = basic["manager"]

    # Step 2b: 东方财富 pingzhongdata（兼容新旧格式）
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

    # Step 2c: 基金代码列表
    flist = get_fund_list_cache()
    if fund_code in flist:
        fi = flist[fund_code]
        if not info.fund_name:
            info.fund_name = fi.get("fundname", "")
        if not info.fund_type:
            info.fund_type = fi.get("type", "")

    # Step 3: 判断是否为被动指数型基金
    info.is_passive = _is_passive_index_fund(info)

    return info


def _is_passive_index_fund(info: FundInfo) -> bool:
    """判断基金是否为被动指数型。

    判断规则（仅当数据库缺失时才使用此逻辑，此时信号来自联网查询）：
    1. tracker_index 非空 → 强信号（权重 3）
    2. fund_type 包含"指数型" → 中等信号（权重 1）
    3. fund_name 包含"指数"和"LOF/ETF" → 强信号（权重 2）
    4. fund_subtype 包含"指数"且不含"增强"/"混合" → 中等信号（权重 1）

    注意：单纯出现 "LOF" 不足以判定为被动型。LOF 只是交易场所形式，
    LOF 可以是指数基金也可以是主动管理型基金。

    Returns
    -------
    bool
    """
    signals = 0

    # Signal 1: 有跟踪指数（最强信号）
    if info.tracker_index and info.tracker_index != "未知指数":
        signals += 3

    # Signal 2: fund_name 包含"指数"（强信号）
    if info.fund_name and "指数" in info.fund_name:
        signals += 2
        if "LOF" in info.fund_name or "ETF" in info.fund_name:
            signals += 1

    # Signal 3: fund_type 包含指数型关键词
    if info.fund_type:
        for kw in ["指数型", "指数"]:
            if kw in info.fund_type:
                signals += 1
                break

    # Signal 4: fund_subtype 包含指数/LOF/ETF
    # 排除含有"增强"、"混合"的 subtype（这些不是纯被动）
    if info.fund_subtype:
        subtype_lower = info.fund_subtype.lower()
        if "指数" in info.fund_subtype and "增强" not in info.fund_subtype:
            signals += 1

    # 至少 2 个信号才认为是被动指数型
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


def _resolve_index_symbol(fund_info) -> Optional[str]:
    """根据基金信息解析需要跟踪的指数代码（如 sz399006）。"""
    tracker_code = getattr(fund_info, 'tracker_index_code', '') or ''
    if not tracker_code:
        return None

    # 使用已有的 INDEX_SYMBOL_MAP 解析
    for keyword, (sym_code, prefix) in INDEX_SYMBOL_MAP.items():
        if keyword in tracker_code or tracker_code in keyword:
            return f"{prefix}{sym_code}"

    # 直接推断
    if len(tracker_code) == 6:
        if tracker_code.startswith("399"):
            return f"sz{tracker_code}"
        if tracker_code.startswith("000"):
            return f"sh{tracker_code}"
        if tracker_code.startswith("930"):
            return f"cn{tracker_code}"
        return f"sh{tracker_code}"
    return None


def _fetch_realtime_index_for_fund(fund_info) -> Optional[float]:
    """获取基金跟踪指数的实时涨跌幅（%）。

    Returns
    -------
    float or None
        指数实时涨跌幅百分比，如 -4.5 表示跌 4.5%
    """
    from fund_estimator.data_sources.sina.realtime import fetch_realtime

    # 优先使用 fund_info 中的 tracker_index_code
    symbol = _resolve_index_symbol(fund_info)

    # fallback：仅在基金不在数据库且无跟踪指数时使用默认指数
    if not symbol:
        symbol = DEFAULT_FALLBACK_INDEX

    try:
        quotes = fetch_realtime([symbol])
        if symbol in quotes:
            q = quotes[symbol]
            if q.prev_close and q.prev_close > 0:
                change_pct = (q.price - q.prev_close) / q.prev_close * 100.0
                return round(change_pct, 4)
    except RuntimeError:
        pass

    return None


def _make_realtime_estimate(
    inputs,
    trade_date: str,
    method: str,
    index_change_pct: float,
    fund_info,
) -> Optional[NAVComparison]:
    """用实时指数涨跌幅构造估值结果。

    这是 estimate_for_day(realtime=True) 的增强版：当盘中历史 K 线无法提供
    今日指数收盘价时，用实时行情计算当日涨跌幅来替代。
    """
    from fund_estimator.backtest.run_backtest import _prev_trading_day
    from fund_estimator.core.models import RealtimeQuote, NAVComparison
    from fund_estimator.estimators.holdings_based import estimate as est_fn

    # T-1 使用最新可用交易日
    latest_date = max(inputs.nav_map.keys())
    t1 = latest_date
    t1_nav = inputs.nav_map[t1]
    if not t1_nav:
        return None

    # 构造实时 quote（仅占位，持仓还原算法需要但实时模式下通常无需实际成分股）
    quotes_today: dict[str, RealtimeQuote] = {}
    quotes_t1: dict[str, RealtimeQuote] = {}

    # 尝试获取实时指数 quote，写入 quotes_today 以便 detail 记录
    symbol = _resolve_index_symbol(fund_info) or DEFAULT_FALLBACK_INDEX
    try:
        from fund_estimator.data_sources.sina.realtime import fetch_realtime
        quotes_idx = fetch_realtime([symbol])
        if symbol in quotes_idx:
            q = quotes_idx[symbol]
            quotes_today[symbol] = RealtimeQuote(
                code=symbol, price=q.price, prev_close=q.prev_close,
                open=q.open, high=q.high, low=q.low,
            )
    except RuntimeError:
        pass

    est = est_fn(
        method,
        fund_code=inputs.fund_code,
        today=trade_date,
        t1_date=t1,
        t1_nav=t1_nav,
        index_change_pct=index_change_pct,
        holdings=inputs.holdings,
        quotes_today=quotes_today,
        quotes_t1=quotes_t1,
    )

    return NAVComparison(
        estimate=est,
        official_nav=None,  # 实时模式无官方 NAV
        official_change_pct=None,
    )


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

    # Step 1: 查询基金信息（优先从本地数据库读取，零网络请求）
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

    # Step 4: 解析基金跟踪的目标指数 symbol
    target_index_symbol = _resolve_index_symbol(fund_info) or DEFAULT_FALLBACK_INDEX

    # Step 5: 执行估值
    # 需要向前扩展日期范围以确保 T-1 数据可用
    # 扩展 30 天以覆盖周末和非交易日
    try:
        trade_dt = datetime.strptime(trade_date, "%Y-%m-%d")
        start_date = (trade_dt - timedelta(days=30)).strftime("%Y-%m-%d")
    except ValueError:
        start_date = ""

    try:
        need_stocks = method in ("v_top10", "v_index_blend", "v_residual_uncovered")
        # 关键修改：将基金跟踪的指数注入 load_common_inputs
        inputs = load_common_inputs(
            fund_code, start_date, trade_date,
            with_holdings=True, with_stocks=need_stocks,
            cache=cache, force=True,
            index_symbol=target_index_symbol,
        )
        comp = estimate_for_day(inputs, trade_date, method, realtime=True)

        if comp is None:
            # 实时估值重试：使用实时指数行情计算当日涨跌幅
            realtime_index_pct = _fetch_realtime_index_for_fund(fund_info)
            if realtime_index_pct is not None:
                comp = _make_realtime_estimate(
                    inputs, trade_date, method, realtime_index_pct, fund_info
                )

            if comp is None:
                return {
                    "success": False,
                    "fund_code": fund_code,
                    "trade_date": trade_date,
                    "error": f"{trade_date} 非交易日或数据缺失，无法估值",
                    "fund_info": fund_info.to_dict(),
                    "method_used": method,
                    "method_reason": reason,
                    "index_symbol_used": target_index_symbol,
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
            "method_used": est.method,
            "method_reason": reason,
            "fund_info": fund_info.to_dict(),
            "index_symbol_used": target_index_symbol,
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
