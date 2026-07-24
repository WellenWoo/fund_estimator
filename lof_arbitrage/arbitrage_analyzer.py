"""
折溢价计算与套利信号分析模块
============================

功能：
    - 计算折价/溢价率
    - 估算套利总成本
    - 生成套利信号（买入/卖出/中性）
    - 评估风险等级
"""

from datetime import datetime
from typing import Optional, Tuple

from .models import FundInfo, NavEstimate, ArbitrageSignal


class ArbitrageAnalyzer:
    """套利信号分析器"""

    def __init__(self,
                 premium_threshold: float = 1.5,
                 discount_threshold: float = -1.5,
                 fee_multiplier: float = 1.2):
        """
        Args:
            premium_threshold: 溢价套利触发阈值（%），场内价格高于净值的比例
            discount_threshold: 折价套利触发阈值（%），场内价格低于净值的比例（负值）
            fee_multiplier: 费率安全系数，实际成本按估算值乘以该系数
        """
        self.premium_threshold = premium_threshold
        self.discount_threshold = discount_threshold
        self.fee_multiplier = fee_multiplier

    def analyze(self, fund: FundInfo, nav_estimate: Optional[NavEstimate] = None) -> ArbitrageSignal:
        """
        分析基金的套利信号

        Args:
            fund: 基金信息（含场内价格）
            nav_estimate: 净值估算结果，None则使用最新确认净值

        Returns:
            ArbitrageSignal 套利信号
        """
        # 确定参考净值
        if nav_estimate and nav_estimate.estimated_nav > 0:
            nav = nav_estimate.estimated_nav
            nav_type = "estimated"
            nav_change = nav_estimate.estimated_change
            confidence = nav_estimate.confidence
        else:
            nav = fund.last_nav
            nav_type = "confirmed"
            nav_change = fund.last_nav_change
            confidence = 1.0

        # 场内价格
        market_price = fund.market_price
        if market_price <= 0:
            # 没有行情数据，使用昨收价
            market_price = fund.market_prev_close

        if market_price <= 0 or nav <= 0:
            return self._no_data_signal(fund)

        # 计算折溢价率
        premium_rate = (market_price - nav) / nav * 100

        # 计算套利总成本
        total_cost = self._calculate_total_cost(fund, premium_rate)

        # 判断信号
        signal, strength, profit_margin = self._determine_signal(
            premium_rate, total_cost, confidence
        )

        # 风险评估
        liquidity_risk = self._assess_liquidity_risk(fund)
        estimation_risk = self._assess_estimation_risk(nav_type, confidence, fund)
        time_risk = self._assess_time_risk(fund)

        # 操作建议
        suggestion = self._generate_suggestion(
            signal, premium_rate, total_cost, profit_margin, fund
        )

        # 触发等级
        trigger_level = self._trigger_level(premium_rate, total_cost)

        return ArbitrageSignal(
            fund_code=fund.code,
            fund_name=fund.name,
            market_price=round(market_price, 4),
            nav=round(nav, 4),
            nav_type=nav_type,
            premium_rate=round(premium_rate, 3),
            total_cost=round(total_cost, 3),
            signal=signal,
            signal_strength=round(strength, 2),
            profit_margin=round(profit_margin, 3),
            liquidity_risk=liquidity_risk,
            estimation_risk=estimation_risk,
            time_risk=time_risk,
            suggestion=suggestion,
            trigger_level=trigger_level,
            update_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        )

    def _calculate_total_cost(self, fund: FundInfo, premium_rate: float) -> float:
        """
        计算套利总成本（%）

        溢价套利成本（场内卖出+场外申购）：
            申购费 + 场内卖出佣金 + 印花税 + 转托管费

        折价套利成本（场内买入+场外赎回）：
            赎回费 + 场内买入佣金 + 转托管费
        """
        commission = fund.trade_commission  # 场内交易佣金
        stamp_tax = fund.stamp_tax          # 印花税

        if premium_rate > 0:
            # 溢价套利：场外申购 -> 场内卖出（T+2完成，约2-3天）
            purchase_fee = fund.purchase_fee if fund.purchase_fee > 0 else 1.5
            sell_commission = commission if commission > 0 else 0.025
            total = purchase_fee + sell_commission + stamp_tax + 0.02  # +转托管费估算
        else:
            # 折价套利：场内买入 -> 场外赎回（T+2完成，持有期约2-3天）
            # 注意：套利持有期短，使用短期赎回费率（<30天）
            redeem_fee = fund.redeem_fee_mid if fund.redeem_fee_mid > 0 else 0.75
            buy_commission = commission if commission > 0 else 0.025
            total = redeem_fee + buy_commission + 0.02  # +转托管费估算

        # 乘以安全系数
        return total * self.fee_multiplier

    def _determine_signal(self, premium_rate: float, total_cost: float,
                          confidence: float) -> Tuple[str, float, float]:
        """
        判断套利信号

        Returns:
            (信号类型, 信号强度0-1, 预期利润率%)
        """
        # 溢价套利：场内价格 - 净值 > 总成本
        if premium_rate > total_cost:
            profit = premium_rate - total_cost
            # 信号强度：利润率 / 阈值，最大1.0
            strength = min(profit / self.premium_threshold, 1.0)
            strength = max(0.1, strength * confidence)
            return "sell_arbitrage", strength, profit

        # 折价套利：净值 - 场内价格 > 总成本（即 premium_rate < -total_cost）
        elif premium_rate < -total_cost:
            profit = abs(premium_rate) - total_cost
            discount_threshold_abs = abs(self.discount_threshold)
            strength = min(profit / discount_threshold_abs, 1.0)
            strength = max(0.1, strength * confidence)
            return "buy_arbitrage", strength, profit

        # 无信号
        else:
            strength = 0.0
            profit = -abs(premium_rate) - total_cost  # 净亏损
            return "neutral", strength, profit

    def _assess_liquidity_risk(self, fund: FundInfo) -> str:
        """评估流动性风险"""
        amount = fund.market_amount  # 成交额（万元）
        if amount >= 1000:
            return "低"
        elif amount >= 100:
            return "中"
        elif amount >= 10:
            return "中高"
        else:
            return "高"

    def _assess_estimation_risk(self, nav_type: str, confidence: float, fund: FundInfo) -> str:
        """评估估值误差风险"""
        if nav_type == "confirmed":
            return "低"
        if confidence >= 0.9:
            return "低"
        elif confidence >= 0.7:
            return "中"
        elif confidence >= 0.5:
            return "中高"
        else:
            return "高"

    def _assess_time_risk(self, fund: FundInfo) -> str:
        """评估时间差风险（T+2套利期间净值波动风险）"""
        # 用近一周的净值波动率估算
        # 简化处理：主动型基金风险高，指数型基金风险中
        fund_type = fund.fund_type or ""
        if "指数" in fund_type or "ETF" in fund_type:
            return "中"
        else:
            return "中高"

    def _generate_suggestion(self, signal: str, premium_rate: float,
                             total_cost: float, profit_margin: float,
                             fund: FundInfo) -> str:
        """生成操作建议"""
        if signal == "sell_arbitrage":
            return (
                f"溢价套利机会：场内价格高于净值 {abs(premium_rate):.2f}%，"
                f"扣除总成本 {total_cost:.2f}% 后预期盈利 {profit_margin:.2f}%。"
                f"建议：场外申购 -> T+1确认 -> T+2转托管场内卖出。"
                f"注意控制仓位，避免冲击成本。"
            )
        elif signal == "buy_arbitrage":
            return (
                f"折价套利机会：场内价格低于净值 {abs(premium_rate):.2f}%，"
                f"扣除总成本 {total_cost:.2f}% 后预期盈利 {profit_margin:.2f}%。"
                f"建议：场内买入 -> T+1转托管场外 -> T+2赎回。"
                f"注意控制仓位，避免冲击成本。"
            )
        else:
            direction = "折价" if premium_rate < 0 else "溢价"
            return (
                f"当前{direction}率为 {abs(premium_rate):.3f}%，"
                f"低于套利总成本 {total_cost:.2f}%，无套利空间。"
                f"建议持续监控，当{direction}率突破 {total_cost:.2f}% 时可考虑操作。"
            )

    def _trigger_level(self, premium_rate: float, total_cost: float) -> str:
        """触发等级"""
        abs_premium = abs(premium_rate)
        if abs_premium >= total_cost * 2:
            return "强"
        elif abs_premium >= total_cost * 1.5:
            return "中"
        elif abs_premium >= total_cost:
            return "弱"
        else:
            return "无"

    def _no_data_signal(self, fund: FundInfo) -> ArbitrageSignal:
        """无数据时的默认信号"""
        return ArbitrageSignal(
            fund_code=fund.code,
            fund_name=fund.name,
            market_price=0,
            nav=0,
            nav_type="unknown",
            premium_rate=0,
            total_cost=0,
            signal="neutral",
            signal_strength=0,
            profit_margin=0,
            liquidity_risk="未知",
            estimation_risk="未知",
            time_risk="未知",
            suggestion="数据获取失败，请检查网络或基金代码。",
            trigger_level="无",
            update_time=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        )
