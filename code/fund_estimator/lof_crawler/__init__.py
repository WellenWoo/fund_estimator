# -*- coding: utf-8 -*-
"""
LOF全量数据采集与价差分析系统

功能:
1. 从天天基金抓取全量基金列表,筛选可场内交易的A类LOF(排除C/D/E/B/I/Y/R份额)
2. 创建SQLite数据库:
   - master_lof: 全部LOF基本信息表
   - lof_detail_{code}: 每个LOF独立数据表(历史净值+历史行情)
3. 计算场内/场外差价,统计Top 100价差最大LOF

数据源:
- 天天基金: 基金列表(fundcode_search.js)
- 东方财富: 历史净值(lsjz API)
- 新浪财经: 历史行情(K线API) + 实时行情
- 腾讯财经: 实时行情(备用)

用法:
    cd E:/api/fund_estimator/code
    python -m fund_estimator.lof_crawler --crawl-all
    python -m fund_estimator.lof_crawler --spread-analysis
    python -m fund_estimator.lof_crawler --help
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sqlite3
import sys
import time
import random
from collections import defaultdict
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta
from typing import Optional

# ---------------------------------------------------------------------------
# Ensure project root is on sys.path
# ---------------------------------------------------------------------------
_THIS = os.path.dirname(os.path.abspath(__file__))
_CODE_ROOT = os.path.dirname(os.path.dirname(_THIS))
if _CODE_ROOT not in sys.path:
    sys.path.insert(0, _CODE_ROOT)

from fund_estimator.data_sources.cache import http_get, CsvCache  # noqa: E402

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DB_DIR = os.path.join(_THIS, "..", "..", "..", "lof_database")
os.makedirs(DB_DIR, exist_ok=True)
DB_PATH = os.path.join(DB_DIR, "lof_master.db")

FUND_LIST_URL = "https://fund.eastmoney.com/js/fundcode_search.js"

# Eastmoney NAV history API
LSJZ_URL = (
    "http://api.fund.eastmoney.com/f10/lsjz"
    "?fundCode={code}&pageIndex={page}&pageSize={size}"
    "&startDate={start}&endDate={end}&_=0"
)
LSJZ_REFERER = "http://fundf10.eastmoney.com/jjjz_{code}.html"

# Sina K-line history API
SINA_KLINE_URL = (
    "https://quotes.sina.cn/cn/api/json_v2.php/CN_MarketDataService.getKLineData"
    "?symbol={symbol}&scale=240&ma=no&datalen={datalen}"
)
SINA_KLINE_REFERER = "https://finance.sina.com.cn"

# Sina realtime API
SINA_RT_URL = "http://hq.sinajs.cn/list={codes}"
SINA_RT_REFERER = "https://finance.sina.com.cn"

# Tencent realtime API (backup)
TENCENT_RT_URL = "http://qt.gtimg.cn/q={codes}"
TENCENT_RT_REFERER = "https://gu.qq.com"
