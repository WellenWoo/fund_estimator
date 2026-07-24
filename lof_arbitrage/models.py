"""
数据模型定义
"""

from dataclasses import dataclass, field
from typing import List, Optional, Dict
from datetime import datetime


@dataclass
class Holding:
    """持仓股票信息"""
    code: str           # 股票代码
    name: str           # 股票名称
    ratio: float        # 占净值比例（%）
    shares: float = 0.0      # 持股数量（万股）
    market_value: float = 0.0 # 持仓市值（万元）
    realtime_price: float = 0.0    # 实时价格
    realtime_change: float = 0.0   # 实时涨跌幅（%）


@dataclass
class FundInfo:
    """基金基本信息"""
    code: str                    # 基金代码
    name: str                    # 基金全称
    short_name: str = ""         # 简称
    fund_type: str = ""          # 类型：主动混合 / 指数联接 / 股票指数
    exchange: str = ""           # 上市交易所：SH / SZ
    manager: str = ""            # 基金经理
    company: str = ""            # 基金公司
    size: float = 0.0            # 净资产规模（亿元）
    shares: float = 0.0          # 份额规模（亿份）
    management_fee: float = 0.0  # 管理费率（%/年）
    custodian_fee: float = 0.0   # 托管费率（%/年）
    tracking_index: str = ""     # 跟踪指数（指数型基金）
    benchmark: str = ""          # 业绩比较基准
    risk_level: str = ""         # 风险等级
    last_nav: float = 0.0        # 最新单位净值
    last_nav_date: str = ""      # 最新净值日期
    last_nav_change: float = 0.0 # 最新净值日涨跌幅（%）
    prev_nav: float = 0.0        # 上一交易日单位净值
    prev_nav_date: str = ""      # 上一交易日净值日期
    # 场内交易数据
    market_price: float = 0.0       # 场内最新价
    market_open: float = 0.0        # 开盘价
    market_high: float = 0.0        # 最高价
    market_low: float = 0.0         # 最低价
    market_prev_close: float = 0.0  # 昨收价
    market_volume: float = 0.0      # 成交量（手）
    market_amount: float = 0.0      # 成交额（万元）
    market_change: float = 0.0      # 场内涨跌幅（%）
    market_update_time: str = ""    # 行情更新时间
    # 持仓
    top_holdings: List[Holding] = field(default_factory=list)
    holdings_date: str = ""       # 持仓数据日期
    # 申赎费率
    purchase_fee: float = 0.0     # 申购费率（%）
    redeem_fee_short: float = 0.0 # 短期赎回费率（%，<7天）
    redeem_fee_mid: float = 0.0   # 中期赎回费率（%，7-30天）
    redeem_fee_long: float = 0.0  # 长期赎回费率（%，>30天）
    trade_commission: float = 0.0 # 场内交易佣金（%，双向）
    stamp_tax: float = 0.05       # 印花税（%，卖出）


@dataclass
class NavEstimate:
    """净值估算结果"""
    fund_code: str
    estimated_nav: float       # 估算净值
    estimated_change: float    # 估算涨跌幅（%）
    algorithm: str             # 使用的算法
    confidence: float          # 置信度 0-1
    update_time: str           # 估值时间
    raw_data: Dict = field(default_factory=dict)  # 原始数据


@dataclass
class ArbitrageSignal:
    """套利信号"""
    fund_code: str
    fund_name: str
    market_price: float
    nav: float                 # 参考净值（确认净值或估算净值）
    nav_type: str              # "confirmed" 或 "estimated"
    premium_rate: float        # 折溢价率（%），正=溢价，负=折价
    total_cost: float          # 套利总成本（%）
    signal: str                # "buy_arbitrage" / "sell_arbitrage" / "neutral"
    signal_strength: float     # 信号强度 0-1
    profit_margin: float       # 预期利润率（%）
    # 风险评估
    liquidity_risk: str = "低" # 流动性风险
    estimation_risk: str = "低" # 估值误差风险
    time_risk: str = "中"      # 时间差风险
    # 建议
    suggestion: str = ""       # 操作建议
    trigger_level: str = ""    # 触发等级
    update_time: str = ""      # 更新时间
