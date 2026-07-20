"""core/models.py — 数据模型

复用 v1.0 的 dataclass 定义,无修改。
"""
from __future__ import annotations
from dataclasses import dataclass, field, asdict
from datetime import date as Date
from typing import Optional


@dataclass
class StockPosition:
    """基金季报披露的单只股票持仓。"""
    code: str            # 6 位股票代码
    name: str
    weight_pct: float    # 占净值比例 (%)
    shares: int = 0      # 持股数
    market_value: float = 0.0  # 持仓市值


@dataclass
class FundHolding:
    """基金全部持仓 (前 N 大)。"""
    fund_code: str
    fund_name: str
    report_date: Date
    positions: list[StockPosition] = field(default_factory=list)
    stock_position_pct: float = 0.0   # 季报披露的总股票仓位 (%)
    cash_position_pct: float = 0.0    # 现金/债券仓位 (%)
    
    def top10(self) -> list[StockPosition]:
        return self.positions[:10]
    
    def coverage_pct(self) -> float:
        """前 10 大持仓合计占净值比 (%)。"""
        return sum(p.weight_pct for p in self.positions[:10])


@dataclass
class RealtimeQuote:
    """实时/今日行情快照。"""
    code: str
    name: str = ""
    prev_close: float = 0.0
    price: float = 0.0
    change_pct: float = 0.0      # 今日涨跌幅 (decimal, e.g. 0.0123 = 1.23%)
    timestamp: str = ""
    
    def is_valid(self) -> bool:
        return self.prev_close > 0 and self.price > 0


@dataclass
class NAVEstimate:
    """单次估值结果。"""
    fund_code: str
    fund_name: str
    today: Date
    t1_date: Date
    t1_nav: float
    estimated_nav: float
    estimated_change_pct: float      # decimal
    method: str
    benchmark: str = ""
    alpha: float = 0.0
    official_nav: Optional[float] = None
    official_change_pct: Optional[float] = None
    
    def error_pp(self) -> Optional[float]:
        """绝对误差 (pp),  None 表示官方 NAV 尚未披露。"""
        if self.official_nav is None:
            return None
        return (self.estimated_nav - self.official_nav) / self.official_nav * 100
    
    def to_dict(self) -> dict:
        d = asdict(self)
        d["today"] = self.today.isoformat()
        d["t1_date"] = self.t1_date.isoformat()
        d["error_pp"] = self.error_pp()
        return d


@dataclass
class NAVComparison:
    """回测一天的对比。"""
    trade_date: Date
    estimated_nav: float
    official_nav: float
    abs_error_pp: float
    method: str
    sign: int   # +1 / -1
