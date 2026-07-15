"""新浪财经数据源。

- realtime.py   实时行情 hq.sinajs.cn (GBK)
- history.py    历史 K 线 CN_MarketDataService
"""

from .realtime import fetch_realtime as fetch_realtime_sina
from .history import fetch_kline, close_on, close_on_in_window

__all__ = [
    "fetch_realtime_sina",
    "fetch_kline",
    "close_on",
    "close_on_in_window",
]
