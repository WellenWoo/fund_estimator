"""本地 CSV 缓存层（TTL 24 小时）+ 统一 HTTP GET 封装。

对齐 README §8 / ITERATIONS.md「数据来源」：
- 缓存目录固定为 ``code/fund_estimator/.cache/``。
- TTL 默认 24 小时；季报披露日可用 ``force=True`` 绕过。
- 仅使用标准库 ``urllib`` + ``csv`` + ``json``。

缓存的价值：历史净值 / 历史日线 / 季报持仓这类「当天内不变」的数据，
第一次抓取后落 CSV，24h 内复用，避免对公开接口的频繁访问（github_code.md §7.1
提到天天基金对单 IP 限频 30~60 req/min）。
"""

from __future__ import annotations

import csv
import gzip
import io
import os
import time
import random
import urllib.request
import urllib.error
from typing import Callable, Iterable, Optional


# --------------------------------------------------------------------------- #
# 缓存目录
# --------------------------------------------------------------------------- #
def cache_dir() -> str:
    """返回 ``code/fund_estimator/.cache/`` 的绝对路径，不存在则创建。"""
    here = os.path.dirname(os.path.abspath(__file__))  # data_sources/
    root = os.path.dirname(here)                        # fund_estimator/
    path = os.path.join(root, ".cache")
    os.makedirs(path, exist_ok=True)
    return path


DEFAULT_TTL = 24 * 3600  # 24 小时


# --------------------------------------------------------------------------- #
# HTTP GET（带 UA 伪装 + GBK 支持 + gzip 解码）
# --------------------------------------------------------------------------- #
_UA_POOL = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36",
]


def http_get(
    url: str,
    *,
    encoding: str = "utf-8",
    referer: Optional[str] = None,
    timeout: float = 15.0,
    retries: int = 3,
) -> str:
    """GET 一个 URL 并返回文本。

    Parameters
    ----------
    encoding:
        响应体解码方式。新浪 / 腾讯实时接口为 ``gbk``。
    referer:
        部分接口（新浪、天天基金）需要伪装 Referer。
    retries:
        失败重试次数，指数退避。
    """
    last_err: Optional[Exception] = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url)
            req.add_header("User-Agent", random.choice(_UA_POOL))
            req.add_header("Accept", "*/*")
            req.add_header("Accept-Encoding", "gzip, deflate")
            if referer:
                req.add_header("Referer", referer)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read()
                if resp.headers.get("Content-Encoding") == "gzip":
                    raw = gzip.decompress(raw)
                return raw.decode(encoding, errors="replace")
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError) as exc:
            last_err = exc
            time.sleep(0.6 * (attempt + 1) + random.random() * 0.4)
    raise RuntimeError(f"HTTP GET failed after {retries} tries: {url} ({last_err})")


# --------------------------------------------------------------------------- #
# CSV 缓存
# --------------------------------------------------------------------------- #
class CsvCache:
    """按「命名空间 + key」缓存二维表格数据到本地 CSV。

    典型用法::

        cache = CsvCache()
        rows = cache.get_or_fetch(
            namespace="nav_history",
            key="160223",
            fetch=lambda: [...],   # 返回 list[dict]
            fieldnames=["date", "nav", "acc_nav", "change_pct"],
        )
    """

    def __init__(self, base_dir: Optional[str] = None, ttl: int = DEFAULT_TTL):
        self.base_dir = base_dir or cache_dir()
        self.ttl = ttl
        os.makedirs(self.base_dir, exist_ok=True)

    # -- 路径 -------------------------------------------------------------- #
    def _path(self, namespace: str, key: str) -> str:
        safe_key = "".join(c if c.isalnum() or c in "-_." else "_" for c in key)
        return os.path.join(self.base_dir, f"{namespace}__{safe_key}.csv")

    # -- 有效性 ------------------------------------------------------------ #
    def is_fresh(self, namespace: str, key: str) -> bool:
        path = self._path(namespace, key)
        if not os.path.exists(path):
            return False
        age = time.time() - os.path.getmtime(path)
        return age < self.ttl

    # -- 读 ---------------------------------------------------------------- #
    def read(self, namespace: str, key: str) -> Optional[list[dict]]:
        path = self._path(namespace, key)
        if not os.path.exists(path):
            return None
        with open(path, "r", encoding="utf-8", newline="") as fh:
            return list(csv.DictReader(fh))

    # -- 写 ---------------------------------------------------------------- #
    def write(self, namespace: str, key: str, rows: Iterable[dict],
              fieldnames: Optional[list[str]] = None) -> None:
        rows = list(rows)
        path = self._path(namespace, key)
        if not fieldnames:
            fieldnames = list(rows[0].keys()) if rows else []
        with open(path, "w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=fieldnames)
            writer.writeheader()
            for r in rows:
                writer.writerow({k: r.get(k, "") for k in fieldnames})

    # -- 核心：读缓存或抓取 ------------------------------------------------ #
    def get_or_fetch(
        self,
        namespace: str,
        key: str,
        fetch: Callable[[], list[dict]],
        fieldnames: Optional[list[str]] = None,
        force: bool = False,
    ) -> list[dict]:
        """若缓存新鲜则直接返回，否则调用 ``fetch`` 抓取并写缓存。

        force=True 时无视 TTL 强制重新抓取（季报披露日用）。
        """
        if not force and self.is_fresh(namespace, key):
            cached = self.read(namespace, key)
            if cached is not None:
                return cached
        rows = fetch()
        if rows:
            self.write(namespace, key, rows, fieldnames)
        return rows

    def clear(self, namespace: Optional[str] = None) -> int:
        """清空缓存。传 namespace 只清该命名空间。返回删除文件数。"""
        n = 0
        for fn in os.listdir(self.base_dir):
            if not fn.endswith(".csv"):
                continue
            if namespace and not fn.startswith(f"{namespace}__"):
                continue
            os.remove(os.path.join(self.base_dir, fn))
            n += 1
        return n


def parse_csv_text(text: str) -> list[dict]:
    """把 CSV 文本解析成 list[dict]（工具函数）。"""
    return list(csv.DictReader(io.StringIO(text)))
