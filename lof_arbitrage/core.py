"""
核心分析模块
============

整合数据获取、净值估算、套利分析的完整流程。
"""

import time
from datetime import datetime
from typing import List, Dict, Optional, Callable
from dataclasses import asdict

from .models import FundInfo, NavEstimate, ArbitrageSignal
from .data_fetcher import DataFetcher
from .nav_estimator import auto_select_estimator, create_estimator
from .arbitrage_analyzer import ArbitrageAnalyzer


class FundAnalyzer:
    """
    单只LOF基金套利分析器

    使用方法：
        analyzer = FundAnalyzer("501098")
        result = analyzer.run()
        print(result)
    """

    def __init__(self, fund_code: str, config: Optional[Dict] = None):
        """
        Args:
            fund_code: 基金代码（6位数字）
            config: 配置字典，可包含：
                - fund_type: 手动指定基金类型（自动推断为None）
                - estimator_type: 手动指定估值器类型
                - estimator_params: 估值器参数
                - premium_threshold: 溢价阈值（%）
                - discount_threshold: 折价阈值（%）
                - fee_multiplier: 费率安全系数
        """
        self.fund_code = fund_code
        self.config = config or {}
        self.fetcher = DataFetcher()
        self.analyzer = ArbitrageAnalyzer(
            premium_threshold=self.config.get("premium_threshold", 1.5),
            discount_threshold=self.config.get("discount_threshold", -1.5),
            fee_multiplier=self.config.get("fee_multiplier", 1.2),
        )

        # 缓存
        self._fund_info: Optional[FundInfo] = None
        self._nav_estimate: Optional[NavEstimate] = None
        self._signal: Optional[ArbitrageSignal] = None

    def fetch_data(self) -> FundInfo:
        """获取基金全部数据"""
        self._fund_info = self.fetcher.fetch_fund_info(self.fund_code)
        return self._fund_info

    def estimate_nav(self) -> NavEstimate:
        """估算实时净值"""
        if self._fund_info is None:
            self.fetch_data()

        fund = self._fund_info

        # 选择估值器
        estimator_type = self.config.get("estimator_type")
        estimator_params = self.config.get("estimator_params", {})

        if estimator_type:
            estimator = create_estimator(estimator_type, self.fetcher, **estimator_params)
        else:
            estimator = auto_select_estimator(fund, self.fetcher)

        self._nav_estimate = estimator.estimate(fund)
        return self._nav_estimate

    def analyze(self) -> ArbitrageSignal:
        """执行套利分析"""
        if self._fund_info is None:
            self.fetch_data()
        if self._nav_estimate is None:
            self.estimate_nav()

        self._signal = self.analyzer.analyze(self._fund_info, self._nav_estimate)
        return self._signal

    def run(self) -> Dict:
        """
        运行完整分析流程

        Returns:
            包含 fund_info, nav_estimate, signal 的字典
        """
        self.fetch_data()
        self.estimate_nav()
        self.analyze()

        return {
            "fund_code": self.fund_code,
            "fund_info": asdict(self._fund_info) if self._fund_info else None,
            "nav_estimate": asdict(self._nav_estimate) if self._nav_estimate else None,
            "signal": asdict(self._signal) if self._signal else None,
            "timestamp": datetime.now().isoformat(),
        }

    @property
    def fund_info(self) -> Optional[FundInfo]:
        return self._fund_info

    @property
    def nav_estimate(self) -> Optional[NavEstimate]:
        return self._nav_estimate

    @property
    def signal(self) -> Optional[ArbitrageSignal]:
        return self._signal


def run_analysis(fund_codes: List[str], config: Optional[Dict] = None,
                 progress_callback: Optional[Callable] = None) -> Dict:
    """
    批量运行多只LOF基金的套利分析

    Args:
        fund_codes: 基金代码列表
        config: 全局配置
        progress_callback: 进度回调函数，签名 callback(current, total, fund_code)

    Returns:
        {
            "results": {code: {...}, ...},
            "summary": {...},
            "timestamp": "..."
        }
    """
    config = config or {}
    results = {}
    total = len(fund_codes)

    for i, code in enumerate(fund_codes, 1):
        if progress_callback:
            progress_callback(i, total, code)

        try:
            analyzer = FundAnalyzer(code, config)
            result = analyzer.run()
            results[code] = result
        except Exception as e:
            results[code] = {
                "fund_code": code,
                "error": str(e),
                "timestamp": datetime.now().isoformat(),
            }

        # 每只基金之间稍作延迟，避免请求过快
        if i < total:
            time.sleep(0.5)

    # 生成汇总
    summary = _generate_summary(results)

    return {
        "results": results,
        "summary": summary,
        "timestamp": datetime.now().isoformat(),
    }


def _generate_summary(results: Dict) -> Dict:
    """生成分析汇总"""
    total = len(results)
    success = 0
    buy_signals = []
    sell_signals = []
    neutral = []
    errors = []

    for code, result in results.items():
        if "error" in result:
            errors.append(code)
            continue

        success += 1
        signal = result.get("signal", {})
        signal_type = signal.get("signal", "neutral")

        if signal_type == "buy_arbitrage":
            buy_signals.append(code)
        elif signal_type == "sell_arbitrage":
            sell_signals.append(code)
        else:
            neutral.append(code)

    return {
        "total": total,
        "success": success,
        "errors": errors,
        "buy_arbitrage_signals": buy_signals,
        "sell_arbitrage_signals": sell_signals,
        "neutral_signals": neutral,
        "arbitrage_opportunities": len(buy_signals) + len(sell_signals),
    }
