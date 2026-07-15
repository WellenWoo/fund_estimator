"""基金实时估值的核心数据模型。

设计原则（对齐 paper_tel.md §2 / README §4 数据流）：
- 全部使用标准库 ``dataclasses``，无第三方依赖。
- 字段命名与 README「数据流」图一致：
  FundHolding（季报持仓）→ RealtimeQuote（实时行情）
  → NAVEstimate（估算净值）→ NAVComparison（对比官方 NAV）。
- 所有金额/比例统一用 ``float``，比例用 0~1（占净值比例）或百分数（涨跌幅 pct）明确标注。
"""

from __future__ import annotations

from dataclasses import dataclass, field, asdict
from typing import Optional


# --------------------------------------------------------------------------- #
# 1. 季报持仓
# --------------------------------------------------------------------------- #
@dataclass
class FundHolding:
    """基金季报披露的单只成分股持仓。

    数据来源：东方财富基金档案 ``FundArchivesDatas.aspx?type=jjcc``。

    Attributes
    ----------
    stock_code:
        6 位股票代码，例如 ``"300750"``（宁德时代）。
    stock_name:
        股票中文简称。
    weight_pct:
        占基金净值比例，单位为百分数（如 ``9.87`` 表示 9.87%）。
    market:
        交易所前缀，``"sh"`` / ``"sz"``；用于拼实时行情代码。
    report_date:
        季报报告期，形如 ``"2026-03-31"``。
    """

    stock_code: str
    stock_name: str
    weight_pct: float
    market: str = ""
    report_date: str = ""

    @property
    def weight(self) -> float:
        """占净值比例（0~1 小数形式）。"""
        return self.weight_pct / 100.0

    @property
    def secid(self) -> str:
        """标准化行情代码，例如 ``sz300750``。"""
        mkt = self.market or _guess_market(self.stock_code)
        return f"{mkt}{self.stock_code}"

    def to_dict(self) -> dict:
        return asdict(self)


# --------------------------------------------------------------------------- #
# 2. 实时行情
# --------------------------------------------------------------------------- #
@dataclass
class RealtimeQuote:
    """单只股票 / 指数的实时（或某交易日收盘）行情快照。

    数据来源：新浪 ``hq.sinajs.cn`` / 腾讯 ``qt.gtimg.cn``（GBK 编码）。

    Attributes
    ----------
    code:
        标准化代码，例如 ``sz399006``（创业板指）、``sz300750``。
    name:
        中文名称。
    price:
        当前价 / 最新价。
    prev_close:
        上一交易日收盘价（用于算涨跌幅）。
    open:
        开盘价。
    high / low:
        当日最高 / 最低。
    volume:
        成交量（股）。
    amount:
        成交额（元）。
    date:
        行情日期（``YYYY-MM-DD``）。
    time:
        行情时间（``HH:MM:SS``），实时快照才有。
    """

    code: str
    name: str = ""
    price: float = 0.0
    prev_close: float = 0.0
    open: float = 0.0
    high: float = 0.0
    low: float = 0.0
    volume: float = 0.0
    amount: float = 0.0
    date: str = ""
    time: str = ""

    @property
    def change_pct(self) -> float:
        """相对上一交易日收盘的涨跌幅，单位百分数（如 -3.10 表示 -3.10%）。"""
        if self.prev_close <= 0:
            return 0.0
        return (self.price - self.prev_close) / self.prev_close * 100.0

    def to_dict(self) -> dict:
        return asdict(self)


# --------------------------------------------------------------------------- #
# 3. 估算净值
# --------------------------------------------------------------------------- #
@dataclass
class NAVEstimate:
    """某交易日的估算净值结果。

    对齐 README §3.1 输出 JSON 字段。

    Attributes
    ----------
    fund_code:
        基金代码，如 ``"160223"``。
    today:
        估值目标交易日（T 日）。
    t1_date:
        基线交易日（T-1 日）。
    t1_nav:
        T-1 日官方单位净值（估值基线）。
    estimated_nav:
        估算出的 T 日单位净值。
    estimated_change_pct:
        估算涨跌幅（相对 T-1），单位百分数。
    method:
        使用的算法标识，如 ``v_index_full_no_cash``。
    detail:
        算法内部中间量（可选，便于调试）。
    """

    fund_code: str
    today: str
    t1_date: str
    t1_nav: float
    estimated_nav: float
    estimated_change_pct: float
    method: str
    detail: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


# --------------------------------------------------------------------------- #
# 4. 估算 vs 官方 对比
# --------------------------------------------------------------------------- #
@dataclass
class NAVComparison:
    """估算净值与官方净值的对比记录（回测 / 生产误差统计单元）。

    Attributes
    ----------
    estimate:
        对应的 NAVEstimate。
    official_nav:
        官方公布的 T 日单位净值（21:00 后才有）。
    official_change_pct:
        官方涨跌幅，单位百分数。
    """

    estimate: NAVEstimate
    official_nav: Optional[float] = None
    official_change_pct: Optional[float] = None

    @property
    def abs_error(self) -> Optional[float]:
        """估算 NAV 与官方 NAV 的绝对差（元）。"""
        if self.official_nav is None:
            return None
        return self.estimate.estimated_nav - self.official_nav

    @property
    def error_pp(self) -> Optional[float]:
        """相对误差，单位百分点 pp = (估算涨跌% - 官方涨跌%)。

        这是 ITERATIONS.md 用来判定「是否超阈值 0.5pp」的核心指标。
        """
        if self.official_nav is None or self.estimate.t1_nav <= 0:
            return None
        est_pct = (self.estimate.estimated_nav - self.estimate.t1_nav) / self.estimate.t1_nav * 100.0
        off_pct = (self.official_nav - self.estimate.t1_nav) / self.estimate.t1_nav * 100.0
        return est_pct - off_pct

    @property
    def over_threshold(self) -> Optional[bool]:
        """是否超过 0.5pp 阈值。"""
        e = self.error_pp
        if e is None:
            return None
        return abs(e) > 0.5

    def to_dict(self) -> dict:
        d = {
            "fund_code": self.estimate.fund_code,
            "today": self.estimate.today,
            "t1_date": self.estimate.t1_date,
            "t1_nav": self.estimate.t1_nav,
            "estimated_nav": self.estimate.estimated_nav,
            "estimated_change_pct": self.estimate.estimated_change_pct,
            "method": self.estimate.method,
            "official_nav": self.official_nav,
            "official_change_pct": self.official_change_pct,
            "abs_error": self.abs_error,
            "error_pp": self.error_pp,
            "over_threshold": self.over_threshold,
        }
        return d


# --------------------------------------------------------------------------- #
# 工具函数
# --------------------------------------------------------------------------- #
def _guess_market(stock_code: str) -> str:
    """根据 6 位股票代码前缀推断交易所前缀。

    规则（A 股常见段）：
    - 6 / 9 开头 → 上交所 ``sh``
    - 0 / 2 / 3 开头 → 深交所 ``sz``
    - 4 / 8 开头 → 北交所（这里仍归 ``bj``，实时源多不支持）
    """
    if not stock_code:
        return "sz"
    head = stock_code[0]
    if head in ("6", "9"):
        return "sh"
    if head in ("4", "8"):
        return "bj"
    return "sz"


THRESHOLD_PP = 0.5
"""单日相对误差合格阈值（百分点），来自 ITERATIONS.md。"""
