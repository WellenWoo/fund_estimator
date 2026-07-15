"""数据源层。

包含本地缓存（cache）以及东方财富 / 新浪 / 腾讯 / 天天基金四个数据源子包。
所有网络访问仅依赖标准库 ``urllib``。
"""

from .cache import CsvCache, cache_dir, http_get

__all__ = ["CsvCache", "cache_dir", "http_get"]
