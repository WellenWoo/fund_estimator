"""core/config.py — 全局配置

改 FUND_CODE 即可迁移到其他基金。
"""
from pathlib import Path
import os

# === 基金配置 ===
FUND_CODE = os.environ.get("FUND_CODE", "160211")
FUND_NAME = "国泰中小盘成长混合(LOF)"

# === 数据源 ===
EAST_FUND_BASE = "https://fundf10.eastmoney.com"
EAST_LSJZ_API = "https://api.fund.eastmoney.com/f10/lsjz"
EAST_PINGZHONG = "https://fund.eastmoney.com/pingzhongdata"

SINA_HQ = "http://hq.sinajs.cn"           # 实时
SINA_HISTORY = "http://quotes.sina.cn/cn/api/json_v2.php"  # 备用
SINA_HISTORY_ALT = "https://quotes.sina.cn/cn/api/jsonp_v2.php/var=CN_MarketDataService.getKLineData"
TENCENT_HQ = "http://qt.gtimg.cn"
TIANTIAN_FUNDGZ = "http://fundgz.1234567.com.cn/js"

# === 候选 benchmark (代码 -> 名称) ===
BENCHMARKS = {
    "csi300":   ("sh000300", "沪深 300"),
    "csi500":   ("sh000905", "中证 500"),
    "csi1000":  ("sh000852", "中证 1000"),
    "cyb":      ("sz399006", "创业板指"),
    "sz50":     ("sh000016", "上证 50"),
}

# 默认 benchmark
DEFAULT_BENCHMARK = "csi1000"

# 默认 alpha (top10 + bench blend 比例, alpha 给 bench)
DEFAULT_ALPHA = 0.5

# === 缓存 ===
CACHE_DIR = Path(__file__).resolve().parent.parent / ".cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)
CACHE_TTL_HOURS = 24

# === 输出 ===
RESULTS_DIR = Path(__file__).resolve().parent.parent / "results"
RESULTS_DIR.mkdir(parents=True, exist_ok=True)
