"""腾讯财经数据源（备用实时行情）。

- realtime.py   qt.gtimg.cn (GBK)
"""

from .realtime import fetch_realtime as fetch_realtime_tencent

__all__ = ["fetch_realtime_tencent"]
