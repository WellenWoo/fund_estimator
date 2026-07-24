"""
LOF基金折价/溢价套利分析工具包
=================================

功能：
    - 获取LOF基金实时净值、持仓、场内交易价格
    - 计算实时估算净值（支持主动型和指数型两种算法）
    - 计算折价/溢价率
    - 输出套利信号
    - 生成分析报告

用法示例：
    from lof_arbitrage import run_analysis
    result = run_analysis(["501098", "160119"])
    print(result)
"""

from .core import run_analysis, FundAnalyzer
from .models import FundInfo, NavEstimate, ArbitrageSignal

__version__ = "1.0.0"
__all__ = [
    "run_analysis",
    "FundAnalyzer",
    "FundInfo",
    "NavEstimate",
    "ArbitrageSignal",
]
