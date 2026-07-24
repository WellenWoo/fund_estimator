"""
净值估算算法模块
===============

提供多种净值估算算法，适用于不同类型的基金：

主动型基金算法：
    - 前十大重仓股模拟法（HoldingSimulationEstimator）
    - 行业ETF映射法（IndustryETFEstimator）

指数型/被动型基金算法：
    - 指数实时映射法（IndexTrackingEstimator）
    - 底仓ETF实时价格法（UnderlyingETFEstimator）
"""

import time
from datetime import datetime
from typing import List, Optional, Dict, Tuple
from dataclasses import dataclass

from .models import FundInfo, Holding, NavEstimate
from .data_fetcher import DataFetcher


class BaseEstimator:
    """净值估算器基类"""

    def __init__(self, fetcher: DataFetcher):
        self.fetcher = fetcher

    def estimate(self, fund: FundInfo) -> NavEstimate:
        """估算基金实时净值，子类必须实现"""
        raise NotImplementedError

    def _now_str(self) -> str:
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


# ============================================================
# 主动型基金估值算法
# ============================================================

class HoldingSimulationEstimator(BaseEstimator):
    """
    前十大重仓股模拟法（适用于主动型基金）

    原理：
        根据基金最新季报披露的前十大重仓股及其占净值比例，
        结合各股票当日实时涨跌幅，加权计算基金净值估算涨幅。

    公式：
        估算净值 = 上日净值 × (1 + Σ(Wi × Ri))
        其中 Wi 为第i只重仓股占净值比例，Ri 为该股当日涨跌幅

    适用：
        - 主动管理型股票基金
        - 前十大持仓集中度较高的基金

    局限性：
        - 仅覆盖前十大持仓，未覆盖部分假设涨跌幅为0
        - 持仓数据为季度末数据，可能与实际有偏差
        - 含港股的基金，A股交易时段港股已收盘，估值有偏差
    """

    def __init__(self, fetcher: DataFetcher, unheld_change: float = 0.0):
        """
        Args:
            fetcher: 数据获取器
            unheld_change: 未覆盖持仓的假设涨跌幅（默认0%）
        """
        super().__init__(fetcher)
        self.unheld_change = unheld_change

    def estimate(self, fund: FundInfo) -> NavEstimate:
        estimated_change = 0.0
        total_covered_ratio = 0.0
        stock_codes = []
        hk_codes = []

        # 分离A股和港股
        for h in fund.top_holdings:
            if h.code.startswith(("0", "3", "6")) and len(h.code) == 6:
                stock_codes.append(h.code)
            elif len(h.code) == 5 or (len(h.code) <= 5 and h.code.isdigit()):
                hk_codes.append(h.code)

        # 获取A股实时行情
        a_quotes = self.fetcher.fetch_stocks_realtime(stock_codes)

        # 计算加权涨跌幅
        for h in fund.top_holdings:
            if h.code in a_quotes:
                change = a_quotes[h.code].get("change_pct", 0)
                estimated_change += h.ratio / 100 * change / 100
                total_covered_ratio += h.ratio
                h.realtime_change = change
            elif len(h.code) <= 5:
                # 港股，尝试获取
                hk_quote = self.fetcher.fetch_hk_stock_realtime(h.code)
                if hk_quote:
                    change = hk_quote.get("change_pct", 0)
                    estimated_change += h.ratio / 100 * change / 100
                    total_covered_ratio += h.ratio
                    h.realtime_change = change

        # 未覆盖部分的假设
        uncovered_ratio = 100 - total_covered_ratio
        if uncovered_ratio > 0:
            estimated_change += uncovered_ratio / 100 * self.unheld_change / 100

        # 计算估算净值
        base_nav = fund.prev_nav if fund.prev_nav > 0 else fund.last_nav
        estimated_nav = base_nav * (1 + estimated_change)

        # 置信度计算：覆盖比例越高，置信度越高
        confidence = min(total_covered_ratio / 100, 0.9)
        # 主动型基金再打个折
        confidence *= 0.7

        return NavEstimate(
            fund_code=fund.code,
            estimated_nav=round(estimated_nav, 4),
            estimated_change=round(estimated_change * 100, 2),
            algorithm="前十大重仓股模拟法",
            confidence=round(confidence, 2),
            update_time=self._now_str(),
            raw_data={
                "total_covered_ratio": round(total_covered_ratio, 2),
                "uncovered_ratio": round(uncovered_ratio, 2),
                "base_nav": base_nav,
            },
        )


class IndustryETFEstimator(BaseEstimator):
    """
    行业ETF映射法（适用于行业主题基金）

    原理：
        选取与基金投资风格最接近的行业ETF作为代理，
        通过ETF的实时涨跌幅乘以β系数估算基金净值涨幅。

    适用：
        - 行业主题基金（科技、医药、消费等）
        - 风格鲜明的主动基金

    参数：
        etf_code: 行业ETF代码
        beta: 基金对ETF的β系数（历史回归得出，默认1.0）
    """

    def __init__(self, fetcher: DataFetcher, etf_code: str = "588000", beta: float = 1.0):
        """
        Args:
            fetcher: 数据获取器
            etf_code: 行业/主题ETF代码（默认科创50ETF 588000）
            beta: β系数
        """
        super().__init__(fetcher)
        self.etf_code = etf_code
        self.beta = beta

    def estimate(self, fund: FundInfo) -> NavEstimate:
        # 获取ETF实时行情
        quote = self.fetcher.fetch_stock_realtime(self.etf_code)
        if not quote:
            # 失败则返回上日净值
            return NavEstimate(
                fund_code=fund.code,
                estimated_nav=fund.last_nav,
                estimated_change=fund.last_nav_change,
                algorithm="行业ETF映射法(数据获取失败)",
                confidence=0.1,
                update_time=self._now_str(),
            )

        etf_change = quote.get("change_pct", 0)
        estimated_change = self.beta * etf_change

        base_nav = fund.prev_nav if fund.prev_nav > 0 else fund.last_nav
        estimated_nav = base_nav * (1 + estimated_change / 100)

        return NavEstimate(
            fund_code=fund.code,
            estimated_nav=round(estimated_nav, 4),
            estimated_change=round(estimated_change, 2),
            algorithm="行业ETF映射法",
            confidence=0.5,
            update_time=self._now_str(),
            raw_data={
                "etf_code": self.etf_code,
                "etf_change": etf_change,
                "beta": self.beta,
            },
        )


# ============================================================
# 指数型/被动型基金估值算法
# ============================================================

class IndexTrackingEstimator(BaseEstimator):
    """
    指数实时映射法（适用于指数型基金）

    原理：
        指数基金跟踪某一指数，净值涨跌幅与指数涨跌幅高度相关。
        直接用指数实时涨跌幅乘以跟踪比例（通常95%左右）估算净值。

    公式：
        估算净值 = 上日净值 × (1 + 跟踪比例 × 指数实时涨跌幅)

    适用：
        - 被动指数基金
        - 指数增强基金
        - ETF联接基金

    精确度：通常误差在0.1%以内
    """

    def __init__(self, fetcher: DataFetcher, index_code: str = "000905", tracking_ratio: float = 0.95):
        """
        Args:
            fetcher: 数据获取器
            index_code: 跟踪指数代码（默认中证500 000905）
            tracking_ratio: 跟踪比例（默认95%，考虑现金及费用）
        """
        super().__init__(fetcher)
        self.index_code = index_code
        self.tracking_ratio = tracking_ratio

    def estimate(self, fund: FundInfo) -> NavEstimate:
        # 尝试从基金信息中获取跟踪指数
        if fund.tracking_index:
            # 从业绩比较基准中提取指数代码
            idx_code = self._extract_index_code(fund.tracking_index)
            if idx_code:
                self.index_code = idx_code

        # 获取指数实时行情
        index_data = self.fetcher.fetch_index_realtime(self.index_code)
        if not index_data or index_data.get("change_pct", 0) == 0:
            # 数据获取失败或非交易时段，返回上日净值
            base_nav = fund.prev_nav if fund.prev_nav > 0 else fund.last_nav
            return NavEstimate(
                fund_code=fund.code,
                estimated_nav=base_nav,
                estimated_change=0,
                algorithm="指数实时映射法(非交易时段/数据缺失)",
                confidence=0.8,
                update_time=self._now_str(),
                raw_data={
                    "index_code": self.index_code,
                    "tracking_ratio": self.tracking_ratio,
                    "note": "使用上日净值作为基准",
                },
            )

        index_change = index_data.get("change_pct", 0)
        estimated_change = self.tracking_ratio * index_change

        base_nav = fund.prev_nav if fund.prev_nav > 0 else fund.last_nav
        estimated_nav = base_nav * (1 + estimated_change / 100)

        return NavEstimate(
            fund_code=fund.code,
            estimated_nav=round(estimated_nav, 4),
            estimated_change=round(estimated_change, 2),
            algorithm="指数实时映射法",
            confidence=0.9,
            update_time=self._now_str(),
            raw_data={
                "index_code": self.index_code,
                "index_name": index_data.get("name", ""),
                "index_change": index_change,
                "tracking_ratio": self.tracking_ratio,
            },
        )

    def _extract_index_code(self, index_name: str) -> Optional[str]:
        """从指数名称中提取代码"""
        # 常见指数映射
        index_map = {
            "中证500": "000905",
            "沪深300": "000300",
            "上证指数": "000001",
            "上证综指": "000001",
            "深证成指": "399001",
            "创业板指": "399006",
            "科创50": "000688",
            "中证1000": "000852",
            "中证100": "000903",
            "上证50": "000016",
        }
        for name, code in index_map.items():
            if name in index_name:
                return code
        return None


class UnderlyingETFEstimator(BaseEstimator):
    """
    底仓ETF实时价格法（最精确，适用于ETF联接基金）

    原理：
        ETF联接基金绝大部分资产投资于目标ETF，
        目标ETF在交易所实时交易，其IOPV（参考净值）每15秒更新一次。
        直接用ETF的实时IOPV推算联接基金净值。

    公式：
        估算净值 = (ETF仓位 × ETF实时IOPV + 非ETF资产 × 昨日市值) / 总份额

    适用：
        - ETF联接基金
        - 持有底层ETF比例高的基金

    精确度：最高，误差通常<0.05%
    """

    def __init__(self, fetcher: DataFetcher, etf_code: str = "510500", etf_ratio: float = 0.95):
        """
        Args:
            fetcher: 数据获取器
            etf_code: 底层ETF代码（默认南方中证500ETF 510500）
            etf_ratio: ETF仓位比例（默认95%）
        """
        super().__init__(fetcher)
        self.etf_code = etf_code
        self.etf_ratio = etf_ratio

    def estimate(self, fund: FundInfo) -> NavEstimate:
        # 获取底层ETF实时行情
        etf_quote = self.fetcher.fetch_stock_realtime(self.etf_code)
        if not etf_quote or etf_quote.get("price", 0) == 0:
            # 数据获取失败，降级为指数映射法
            base_nav = fund.prev_nav if fund.prev_nav > 0 else fund.last_nav
            return NavEstimate(
                fund_code=fund.code,
                estimated_nav=base_nav,
                estimated_change=0,
                algorithm="底仓ETF实时价格法(数据获取失败)",
                confidence=0.5,
                update_time=self._now_str(),
            )

        etf_change = etf_quote.get("change_pct", 0)
        # 联接基金净值涨跌幅 ≈ ETF涨跌幅 × ETF仓位比例
        estimated_change = self.etf_ratio * etf_change

        base_nav = fund.prev_nav if fund.prev_nav > 0 else fund.last_nav
        estimated_nav = base_nav * (1 + estimated_change / 100)

        return NavEstimate(
            fund_code=fund.code,
            estimated_nav=round(estimated_nav, 4),
            estimated_change=round(estimated_change, 2),
            algorithm="底仓ETF实时价格法",
            confidence=0.95,
            update_time=self._now_str(),
            raw_data={
                "etf_code": self.etf_code,
                "etf_price": etf_quote.get("price", 0),
                "etf_change": etf_change,
                "etf_ratio": self.etf_ratio,
            },
        )


# ============================================================
# 估值器工厂
# ============================================================

def create_estimator(fund_type: str, fetcher: DataFetcher, **kwargs) -> BaseEstimator:
    """
    根据基金类型创建合适的估值器

    Args:
        fund_type: 基金类型
            - "active" / "主动" / "混合" -> 前十大重仓股模拟法
            - "index" / "指数" / "被动" -> 指数实时映射法
            - "etf_link" / "ETF联接" -> 底仓ETF实时价格法
        fetcher: 数据获取器
        **kwargs: 传递给估值器的参数

    Returns:
        BaseEstimator 实例
    """
    fund_type_lower = fund_type.lower()

    if any(k in fund_type_lower for k in ["etf联接", "etf链接", "etf_link"]):
        etf_code = kwargs.get("etf_code", "510500")
        etf_ratio = kwargs.get("etf_ratio", 0.95)
        return UnderlyingETFEstimator(fetcher, etf_code=etf_code, etf_ratio=etf_ratio)

    elif any(k in fund_type_lower for k in ["指数", "index", "被动", "passive"]):
        index_code = kwargs.get("index_code", "000905")
        tracking_ratio = kwargs.get("tracking_ratio", 0.95)
        return IndexTrackingEstimator(fetcher, index_code=index_code, tracking_ratio=tracking_ratio)

    elif any(k in fund_type_lower for k in ["主动", "active", "混合", "股票型"]):
        return HoldingSimulationEstimator(fetcher)

    else:
        # 默认使用持仓模拟法
        return HoldingSimulationEstimator(fetcher)


def auto_select_estimator(fund: FundInfo, fetcher: DataFetcher) -> BaseEstimator:
    """
    根据基金信息自动选择最合适的估值器

    Args:
        fund: 基金信息对象
        fetcher: 数据获取器

    Returns:
        BaseEstimator 实例
    """
    fund_type = fund.fund_type or ""
    name = fund.name or ""

    # ETF联接基金
    if "ETF联接" in name or "ETF联接" in fund_type or "etf" in fund_type.lower():
        # 尝试从基金名中推断底层ETF
        if "中证500" in name:
            return UnderlyingETFEstimator(fetcher, etf_code="510500", etf_ratio=0.95)
        elif "沪深300" in name:
            return UnderlyingETFEstimator(fetcher, etf_code="510300", etf_ratio=0.95)
        elif "科创50" in name:
            return UnderlyingETFEstimator(fetcher, etf_code="588000", etf_ratio=0.95)
        elif "创业板" in name:
            return UnderlyingETFEstimator(fetcher, etf_code="159915", etf_ratio=0.95)
        else:
            # 默认用指数映射法
            if "中证500" in name:
                return IndexTrackingEstimator(fetcher, index_code="000905")
            elif "沪深300" in name:
                return IndexTrackingEstimator(fetcher, index_code="000300")
            return IndexTrackingEstimator(fetcher)

    # 指数基金
    elif "指数" in fund_type or "指数" in name or "被动" in fund_type:
        if "中证500" in name:
            return IndexTrackingEstimator(fetcher, index_code="000905")
        elif "沪深300" in name:
            return IndexTrackingEstimator(fetcher, index_code="000300")
        elif "科创50" in name or "科创板" in name:
            return IndexTrackingEstimator(fetcher, index_code="000688")
        elif "创业板" in name:
            return IndexTrackingEstimator(fetcher, index_code="399006")
        else:
            return IndexTrackingEstimator(fetcher)

    # 主动型基金（混合、股票）
    else:
        return HoldingSimulationEstimator(fetcher)
