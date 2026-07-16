"""核心数据模型。

基金实时估值的"原料"和"产物"统一用 dataclass 表示，便于做计算、对比、序列化。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional


@dataclass
class StockPosition:
    """单只股票的持仓。"""

    code: str  # 6 位股票代码，如 "300750"
    name: str = ""
    shares: float = 0.0  # 持有股数（万股）
    market_value_ratio: float = 0.0  # 占基金净值比例（%）
    market: str = "SZ"  # SZ / SH

    @property
    def new_market_code(self) -> str:
        """东方财富用的 secid 格式：0.300750 / 1.600519"""
        return f"{0 if self.market == 'SZ' else 1}.{self.code}"


@dataclass
class FundHolding:
    """一只基金在某报告期内的全部持仓快照。"""

    fund_code: str
    fund_name: str
    report_date: date  # 季报/半年报/年报披露的报告日
    disclose_date: date  # 实际披露日期
    stock_positions: list[StockPosition] = field(default_factory=list)
    stock_position_pct: float = 0.0  # 股票占净值比（%），例如 95.0
    total_share: float = 0.0  # 总份额（亿份），可选
    source: str = ""  # 数据来源标记


@dataclass
class RealtimeQuote:
    """某只股票/基金的实时行情快照。"""

    code: str
    market: str  # SZ/SH
    name: str = ""
    price: float = 0.0  # 当前价
    prev_close: float = 0.0  # 昨收
    open: float = 0.0
    high: float = 0.0
    low: float = 0.0
    timestamp: datetime = field(default_factory=datetime.now)

    @property
    def change_pct(self) -> float:
        """涨跌幅 %。"""
        if self.prev_close <= 0:
            return 0.0
        return (self.price - self.prev_close) / self.prev_close * 100.0


@dataclass
class NAVEstimate:
    """估值结果输出。"""

    fund_code: str
    estimate_time: datetime
    estimated_nav: float  # 估算净值
    estimated_change_pct: float  # 估算涨跌幅 %
    method: str  # 用了什么算法
    components: dict = field(default_factory=dict)  # 每个股票/部分的贡献明细

    def to_dict(self) -> dict:
        return {
            "fund_code": self.fund_code,
            "estimate_time": self.estimate_time.isoformat(),
            "estimated_nav": round(self.estimated_nav, 4),
            "estimated_change_pct": round(self.estimated_change_pct, 4),
            "method": self.method,
            "components": self.components,
        }


@dataclass
class NAVComparison:
    """估值 vs 官方净值的对比结果。"""

    fund_code: str
    trade_date: date
    estimated_nav: float
    official_nav: float
    abs_error: float  # |estimate - official|
    rel_error_pct: float  # (estimate - official) / official * 100%
    method: str

    @classmethod
    def make(
        cls,
        fund_code: str,
        trade_date: date,
        estimated_nav: float,
        official_nav: float,
        method: str,
    ) -> "NAVComparison":
        diff = estimated_nav - official_nav
        abs_err = abs(diff)
        rel = (diff / official_nav * 100.0) if official_nav > 0 else 0.0
        return cls(
            fund_code=fund_code,
            trade_date=trade_date,
            estimated_nav=estimated_nav,
            official_nav=official_nav,
            abs_error=round(abs_err, 6),
            rel_error_pct=round(rel, 4),
            method=method,
        )
