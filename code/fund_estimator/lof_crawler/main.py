# -*- coding: utf-8 -*-
"""
LOF全量数据采集与价差分析 - 主实现 v2

Phase 1: LOF发现与主数据库
Phase 2: 逐基金历史数据表 (NAV + 市场成交价)
Phase 3: 价差分析
Phase 4: 输出报告
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import sys
import time
import random
from datetime import datetime
from typing import Optional

from ..data_sources.cache import http_get

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

_LOF_CRAWLER_DIR = os.path.dirname(os.path.abspath(__file__))
# lof_crawler/ → fund_estimator/ → code/ → project root is one level above code/
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(_LOF_CRAWLER_DIR)))
_DB_DIR_DEFAULT = os.path.join(_PROJECT_ROOT, "lof_database")
_DB_PATH_DEFAULT = os.path.join(_DB_DIR_DEFAULT, "lof_master.db")

DB_DIR = os.environ.get("LOF_DB_DIR", _DB_DIR_DEFAULT)
DB_PATH = os.environ.get("LOF_DB_PATH", _DB_PATH_DEFAULT)

FUND_LIST_URL = "https://fund.eastmoney.com/js/fundcode_search.js"

# Eastmoney NAV history API
LSJZ_URL = (
    "http://api.fund.eastmoney.com/f10/lsjz"
    "?fundCode={code}&pageIndex={page}&pageSize={size}"
    "&startDate={start}&endDate={end}&_=0"
)
LSJZ_REFERER = "http://fundf10.eastmoney.com/jjjz_{code}.html"

# Sina K-line API (for market price history)
SINA_KLINE_URL = (
    "https://quotes.sina.cn/cn/api/json_v2.php/CN_MarketDataService.getKLineData"
    "?symbol={symbol}&scale=240&ma=no&datalen={datalen}"
)
SINA_KLINE_REFERER = "https://finance.sina.com.cn"

# Sina realtime API (fund)
SINA_RT_URL = "http://hq.sinajs.cn/list={codes}"
SINA_RT_REFERER = "https://finance.sina.com.cn"

# Tencent realtime API (fund backup)
TENCENT_RT_URL = "http://qt.gtimg.cn/q={codes}"
TENCENT_RT_REFERER = "https://gu.qq.com"

# Eastmoney fund estimate API
FUND_GZ_URL = "http://fundgz.1234567.com.cn/js/{code}.js"


# ===========================================================================
# Phase 1: LOF Discovery & Master Database
# ===========================================================================

def fetch_fund_list() -> list[dict]:
    """从天天基金获取全市场基金代码列表。"""
    text = http_get(FUND_LIST_URL, encoding="utf-8")
    m = re.search(r'var\s+r\s*=\s*\[', text)
    if not m:
        raise RuntimeError("Cannot parse fundcode_search.js")
    start = m.end() - 1
    depth = 0
    end = start
    for i in range(start, len(text)):
        if text[i] == '[':
            depth += 1
        elif text[i] == ']':
            depth -= 1
            if depth == 0:
                end = i
                break
    data = json.loads(text[start:end + 1])
    results = []
    for item in data:
        if isinstance(item, (list, tuple)) and len(item) >= 5:
            results.append({
                "fundcode": str(item[0]),
                "fundname": str(item[2]),
                "fundtype": str(item[3]),
                "fullname": str(item[4]),
                "pinyin": str(item[1]),
            })
    return results


def filter_tradable_lofs(fund_list: list[dict]) -> list[dict]:
    """筛选可场内交易的A类LOF。"""
    candidates = []
    for fund in fund_list:
        name = fund["fundname"]
        if 'LOF' not in name and 'lof' not in name:
            continue
        if 'FOF' in name or 'fof' in name:
            continue
        if 'QDII' in name or 'qdii' in name:
            continue
        upper_name = name.upper()

        # Exclude share class variants C/D/E/B/I/Y/R
        excludes = ['(LOF)C','(LOF)E','(LOF)D','(LOF)I','(LOF)Y','(LOF)R',
                     'LOFC','LOFE','LOFD','LOFI','LOFY','LOFR']
        skip = any(s in upper_name for s in excludes)
        if skip:
            continue

        # Must be A-share or no suffix (BASE)
        if '(LOF)A' not in upper_name and 'LOFA' not in upper_name \
                and 'A(' not in upper_name and '后端' not in name \
                and not _is_base_lof(name):
            continue

        if '货币' in name:
            continue
        if '债券' in name and '指数' not in name:
            continue

        candidates.append(fund)

    return _dedup_lofs(candidates)


def _is_base_lof(name: str) -> bool:
    """判断是否为无后缀的基础LOF（即默认A类）。"""
    # Funds with (LOF) at end without letter suffix
    if re.search(r'\(LOF\)\s*$', name, re.IGNORECASE):
        return True
    # Funds with (LOF)A(后缀) pattern
    if re.search(r'\(LOF\)A[\(\[]', name):
        return True
    return False


def _dedup_lofs(candidates: list[dict]) -> list[dict]:
    """去重: 同一基金的不同份额只保留A类。"""
    seen = {}
    for fund in candidates:
        norm = re.sub(r'\(LOF\)A?\s*[\(\[].*?[\)\]]', '', fund["fundname"], flags=re.IGNORECASE)
        norm = re.sub(r'\(LOF\)$', '', norm, flags=re.IGNORECASE)
        norm = re.sub(r'LOF$', '', norm, flags=re.IGNORECASE)
        norm = re.sub(r'^\s+|\s+$', '', norm)
        if norm not in seen:
            seen[norm] = fund
    return list(seen.values())


def create_master_db(lof_list: list[dict]) -> str:
    """创建SQLite主数据库,建立master_lof表。"""
    os.makedirs(DB_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("DROP TABLE IF EXISTS master_lof")

    cursor.execute("""
        CREATE TABLE master_lof (
            fund_code TEXT PRIMARY KEY,
            fund_name TEXT NOT NULL,
            fund_type TEXT,
            full_name TEXT,
            pinyin TEXT,
            share_class TEXT DEFAULT 'A',
            is_index_fund INTEGER DEFAULT 0,
            tracker_index TEXT DEFAULT '',
            tracker_index_code TEXT DEFAULT '',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)

    for fund in lof_list:
        is_index = 1 if ('指数' in fund["fundname"] or 'ETF联接' in fund["fundname"]
                         or '指数增' in fund["fundname"]) else 0
        cursor.execute("""
            INSERT INTO master_lof
            (fund_code, fund_name, fund_type, full_name, pinyin, share_class, is_index_fund)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (fund["fundcode"], fund["fundname"], fund["fundtype"],
              fund.get("fullname", ""), fund.get("pinyin", ""), "A", is_index))

    conn.commit()
    cursor.execute("SELECT COUNT(*) FROM master_lof")
    count = cursor.fetchone()[0]
    print(f"  Created master_lof table with {count} LOFs")
    conn.close()
    return DB_PATH


def fetch_fund_detail_from_eastmoney(fund_code: str) -> dict:
    """从东方财富pingzhongdata获取基金详细信息。"""
    info = {}
    try:
        url = f"http://fund.eastmoney.com/pingzhongdata/{fund_code}.js"
        text = http_get(url, encoding="utf-8", referer="http://fund.eastmoney.com/")

        def _extract(var_name: str) -> Optional[str]:
            m = re.search(rf'var\s+{var_name}\s*=\s*"([^"]*)"', text)
            if m: return m.group(1).strip()
            m = re.search(rf"var\s+{var_name}\s*=\s*'([^']*)'", text)
            if m: return m.group(1).strip()
            return None

        info["indexname"] = _extract("indexname") or ""
        info["indexcode"] = _extract("indexcode") or ""
        if not info["indexname"]:
            info["indexname"] = _extract("fS_indexname") or ""
            info["indexcode"] = _extract("fS_indexcode") or ""
    except Exception:
        pass
    return info


def update_master_db_with_details() -> None:
    """更新master_lof表,补充跟踪指数等详细信息。"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("SELECT fund_code, fund_name FROM master_lof")
    funds = cursor.fetchall()

    updated = 0
    for fund_code, fund_name in funds:
        detail = fetch_fund_detail_from_eastmoney(fund_code)
        tracker_index = detail.get("indexname", "")
        tracker_index_code = detail.get("indexcode", "")

        if tracker_index and tracker_index != "未知指数":
            is_index = 1
        elif '指数' in fund_name or 'ETF联接' in fund_name:
            is_index = 1
        else:
            is_index = 0

        cursor.execute("""
            UPDATE master_lof
            SET tracker_index = ?, tracker_index_code = ?, is_index_fund = ?
            WHERE fund_code = ?
        """, (tracker_index, tracker_index_code, is_index, fund_code))
        updated += 1

        if updated % 10 == 0:
            time.sleep(0.5 + random.random() * 0.5)

    conn.commit()
    print(f"  Updated {updated} fund records with details")
    conn.close()


# ===========================================================================
# Phase 2: Per-Fund Historical Data Tables
# ===========================================================================

def detect_exchange_prefix(fund_code: str) -> str:
    """根据基金代码前缀判断交易所前缀。

    - 16xxxx → sz (深交所LOF)
    - 50xxxx → sh (上交所LOF)
    - 00xxxx/11xxxx/13xxxx/14xxxx/15xxxx → 需要逐个测试
    """
    code = fund_code[:6]
    if code.startswith('16'):
        return 'sz'
    elif code.startswith('50'):
        return 'sh'
    elif code.startswith('00') or code.startswith('11') or code.startswith('13') or code.startswith('14') or code.startswith('15'):
        # These newer LOF codes could be either; try sh first
        return 'sh'
    else:
        return 'sz'


def get_sina_symbol_for_fund(fund_code: str) -> str:
    """构建新浪财经symbol。"""
    prefix = detect_exchange_prefix(fund_code)
    return f"{prefix}{fund_code[:6]}"


def fetch_nav_history(fund_code: str, start: str = "2021-01-01", end: str = "2026-12-31", max_pages: int = 300) -> list[dict]:
    """从东方财富抓取历史净值。

    Parameters
    ----------
    fund_code: 基金代码
    start: 起始日期 (默认近5年)
    end: 结束日期
    max_pages: 最大翻页数
    """
    all_rows = []
    page = 1
    size = 20

    while True:
        url = LSJZ_URL.format(code=fund_code, page=page, size=size, start=start, end=end)
        try:
            text = http_get(url, encoding="utf-8", referer=LSJZ_REFERER.format(code=fund_code))
        except Exception:
            break

        cleaned = text.strip()
        if not cleaned.startswith("{"):
            cleaned = re.sub(r'^[^{]*|[^}]*$', '', cleaned, flags=re.DOTALL)
        try:
            data = json.loads(cleaned)
        except json.JSONDecodeError:
            break

        payload = data.get("Data") or {}
        lst = payload.get("LSJZList") or []
        total = int(data.get("TotalCount") or payload.get("TotalCount") or len(lst))

        if not lst:
            break

        for item in lst:
            try:
                nav = float(item.get("DWJZ", 0))
            except (TypeError, ValueError):
                continue
            all_rows.append({
                "date": item.get("FSRQ", ""),
                "nav": nav,
                "acc_nav": float(item.get("LJJZ", nav)) if item.get("LJJZ") else nav,
                "change_pct": float(item.get("JZZZL", 0)) if item.get("JZZZL") else 0.0,
            })

        if len(all_rows) >= total or len(lst) < size:
            break
        page += 1
        if page > max_pages:
            break
        time.sleep(0.2 + random.random() * 0.2)

    seen = {}
    for r in all_rows:
        if r["date"]:
            seen[r["date"]] = r
    return sorted(seen.values(), key=lambda r: r["date"])


def fetch_market_price_via_sina_kline(fund_code: str, datalen: int = 1023) -> list[dict]:
    """从新浪财经K线接口抓取历史成交价。"""
    symbol = get_sina_symbol_for_fund(fund_code)
    rows = []
    try:
        url = SINA_KLINE_URL.format(symbol=symbol, datalen=datalen)
        text = http_get(url, encoding="utf-8", referer=SINA_KLINE_REFERER)
        m = re.search(r'\[.*\]', text, re.DOTALL)
        if not m:
            return []
        arr = json.loads(m.group(0))
        for it in arr:
            day = it.get("day", "")
            date = day.split(" ")[0] if day else ""
            try:
                rows.append({
                    "date": date,
                    "market_price": float(it.get("close", 0)),
                    "volume": float(it.get("volume", 0)),
                })
            except (TypeError, ValueError):
                continue
    except Exception:
        pass
    return sorted(rows, key=lambda r: r["date"])


def fetch_market_price_via_tencent(fund_code: str) -> Optional[dict]:
    """从腾讯实时接口获取最新成交价和净值(用于验证)。"""
    symbol = get_sina_symbol_for_fund(fund_code)
    try:
        url = TENCENT_RT_URL.format(codes=symbol)
        text = http_get(url, encoding="gbk", referer=TENCENT_RT_REFERER)
        # Format: v_sz160105="51~南方积配LOF~160105~1.245~1.260~1.268~...~1.2789~..."
        m = re.search(rf'v_{re.escape(symbol)}="(?P<body>[^"]*)"', text)
        if m:
            parts = m.group("body").split("~")
            if len(parts) >= 45:
                return {
                    "market_price": float(parts[3]) if parts[3] else 0,
                    "prev_close": float(parts[4]) if parts[4] else 0,
                    "open": float(parts[5]) if parts[5] else 0,
                    "high": float(parts[33]) if len(parts) > 33 and parts[33] else 0,
                    "low": float(parts[34]) if len(parts) > 34 and parts[34] else 0,
                    "nav": float(parts[44]) if len(parts) > 44 and parts[44] else 0,
                    "volume": float(parts[6]) if len(parts) > 6 and parts[6] else 0,
                    "timestamp": parts[30] if len(parts) > 30 else "",
                }
    except Exception:
        pass
    return None


def create_fund_detail_table(cursor: sqlite3.Connection, fund_code: str) -> None:
    """为单个LOF创建详细数据表。"""
    table_name = f"lof_detail_{fund_code}"
    cursor.execute(f"""
        CREATE TABLE IF NOT EXISTS {table_name} (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fund_code TEXT NOT NULL,
            date TEXT NOT NULL,
            nav REAL,
            acc_nav REAL,
            change_pct REAL,
            market_price REAL,
            premium_discount REAL,
            volume REAL,
            amount REAL,
            source TEXT DEFAULT 'combined',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)


def store_fund_data(fund_code: str, nav_rows: list[dict], price_rows: list[dict]) -> int:
    """将NAV和行情数据存储到detail表,合并计算溢价折价率。"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    create_fund_detail_table(cursor, fund_code)

    price_map = {pr["date"]: pr for pr in price_rows}

    inserted = 0
    for nav_row in nav_rows:
        date = nav_row["date"]
        nav = nav_row["nav"]
        acc_nav = nav_row["acc_nav"]
        change_pct = nav_row["change_pct"]

        price_info = price_map.get(date, {})
        market_price = price_info.get("market_price", 0)
        volume = price_info.get("volume", 0)
        amount = market_price * volume if market_price and volume else 0

        premium_discount = 0.0
        if nav and nav > 0 and market_price > 0:
            premium_discount = (market_price - nav) / nav * 100.0

        cursor.execute(f"""
            INSERT INTO lof_detail_{fund_code}
            (fund_code, date, nav, acc_nav, change_pct, market_price, premium_discount, volume, amount)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (fund_code, date, nav, acc_nav, change_pct, market_price, premium_discount, volume, amount))
        inserted += 1

    conn.commit()
    conn.close()
    return inserted


def crawl_fund_history(fund_code: str) -> dict:
    """抓取单个LOF的完整历史数据。"""
    # Fetch NAV history (full history)
    # Use 5-year date range for reasonable crawl speed
    nav_rows = fetch_nav_history(fund_code, start="2021-01-01", end="2026-12-31")
    if not nav_rows:
        # Fall back to full history if 5-year window returns nothing
        nav_rows = fetch_nav_history(fund_code, start="", end="")
    if not nav_rows:
        return {"success": False, "nav_count": 0, "price_count": 0, "error": "No NAV data"}

    # Fetch market price via Sina K-line
    price_rows = fetch_market_price_via_sina_kline(fund_code, datalen=1023)

    # If Sina K-line returns nothing, try alternate exchange prefix
    if not price_rows:
        alt_prefix = 'sh' if detect_exchange_prefix(fund_code) == 'sz' else 'sz'
        alt_symbol = f"{alt_prefix}{fund_code[:6]}"
        try:
            url = SINA_KLINE_URL.format(symbol=alt_symbol, datalen=1023)
            text = http_get(url, encoding="utf-8", referer=SINA_KLINE_REFERER)
            m = re.search(r'\[.*\]', text, re.DOTALL)
            if m:
                arr = json.loads(m.group(0))
                price_rows = []
                for it in arr:
                    day = it.get("day", "").split(" ")[0]
                    try:
                        price_rows.append({
                            "date": day,
                            "market_price": float(it.get("close", 0)),
                            "volume": float(it.get("volume", 0)),
                        })
                    except: continue
                if price_rows:
                    print(f"    Using alternate symbol {alt_symbol} for {fund_code}")
        except: pass

    inserted = store_fund_data(fund_code, nav_rows, price_rows)
    return {
        "success": inserted > 0,
        "nav_count": len(nav_rows),
        "price_count": len(price_rows),
        "merged_count": inserted,
    }


def crawl_all_fund_histories(lof_codes: list[str], batch_sleep: float = 1.5, max_funds: Optional[int] = None) -> dict:
    """批量抓取所有LOF的历史数据。

    Parameters
    ----------
    lof_codes: LOF代码列表
    batch_sleep: 每5只基金后的休眠时间(秒)
    max_funds: 限制抓取数量(None=全部)
    """
    if max_funds:
        lof_codes = lof_codes[:max_funds]
    
    results = {}
    total = len(lof_codes)

    for i, fund_code in enumerate(lof_codes):
        print(f"  [{i+1}/{total}] Crawling {fund_code}...")
        try:
            result = crawl_fund_history(fund_code)
            results[fund_code] = result
        except Exception as e:
            results[fund_code] = {
                "success": False, "nav_count": 0, "price_count": 0,
                "error": str(e),
            }

        if (i + 1) % 10 == 0:
            sleep_time = batch_sleep + random.random() * 1
            print(f"    Sleeping {sleep_time:.1f}s for rate limiting...")
            time.sleep(sleep_time)

    success_count = sum(1 for r in results.values() if r.get("success"))
    print(f"\n  Crawl complete: {success_count}/{total} funds successful")
    return results


# ===========================================================================
# Phase 3: Spread Analysis
# ===========================================================================

def compute_spread_statistics() -> list[dict]:
    """计算每个LOF的溢价/折价统计指标。"""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    cursor.execute("SELECT fund_code, fund_name FROM master_lof")
    funds = cursor.fetchall()

    stats_list = []
    for fund_code, fund_name in funds:
        table_name = f"lof_detail_{fund_code}"

        cursor.execute("""
            SELECT COUNT(*) FROM sqlite_master
            WHERE type='table' AND name=?
        """, (table_name,))
        if cursor.fetchone()[0] == 0:
            continue

        cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
        row_count = cursor.fetchone()[0]
        if row_count < 10:
            continue

        cursor.execute(f"""
            SELECT
                COUNT(*) as data_points,
                AVG(premium_discount) as avg_premium,
                MAX(premium_discount) as max_premium,
                MIN(premium_discount) as min_premium,
                AVG(ABS(premium_discount)) as avg_absolute_premium,
                MAX(ABS(premium_discount)) as max_absolute_premium,
                SUM(CASE WHEN premium_discount > 0 THEN 1 ELSE 0 END) as positive_days,
                SUM(CASE WHEN premium_discount < 0 THEN 1 ELSE 0 END) as negative_days,
                AVG(nav) as avg_nav,
                AVG(market_price) as avg_market_price
            FROM {table_name}
            WHERE nav > 0 AND market_price > 0
        """)
        row = cursor.fetchone()

        if row and row[0] and row[1] is not None:
            dp = row[0]
            avg_prem = row[1] or 0
            max_prem = row[2] or 0
            min_prem = row[3] or 0
            avg_abs = row[4] or 0
            max_abs = row[5] or 0
            pos = row[6] or 0
            neg = row[7] or 0
            avg_nav = row[8] or 0
            avg_mp = row[9] or 0

            stats_list.append({
                "fund_code": fund_code,
                "fund_name": fund_name,
                "data_points": dp,
                "avg_premium_pct": round(avg_prem, 4),
                "max_premium_pct": round(max_prem, 4),
                "min_premium_pct": round(min_prem, 4),
                "avg_absolute_premium_pct": round(avg_abs, 4),
                "max_absolute_premium_pct": round(max_abs, 4),
                "positive_days": pos,
                "negative_days": neg,
                "avg_nav": round(avg_nav, 4),
                "avg_market_price": round(avg_mp, 4),
                "premium_frequency": round(pos / dp * 100, 2) if dp > 0 else 0,
            })

    conn.close()
    stats_list.sort(key=lambda x: x["avg_absolute_premium_pct"], reverse=True)
    print(f"  Computed spread statistics for {len(stats_list)} LOFs with data")
    return stats_list


def get_top_n_spread(n: int = 100) -> list[dict]:
    """获取价差最大的前N个LOF。"""
    stats = compute_spread_statistics()
    return stats[:n]


# ===========================================================================
# Phase 4: Output & Reporting
# ===========================================================================

def save_top_n_results(top_n: list[dict], filepath: Optional[str] = None) -> str:
    """将Top N结果保存到SQLite和JSON。"""
    if filepath is None:
        filepath = os.path.join(DB_DIR, "top_spread_lofs.json")

    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(top_n, f, ensure_ascii=False, indent=2)
    print(f"  Saved Top {len(top_n)} results to {filepath}")

    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.execute("DROP TABLE IF EXISTS top_spread_ranking")
    cursor.execute("""
        CREATE TABLE top_spread_ranking (
            rank INTEGER PRIMARY KEY,
            fund_code TEXT NOT NULL,
            fund_name TEXT NOT NULL,
            data_points INTEGER,
            avg_premium_pct REAL,
            max_premium_pct REAL,
            min_premium_pct REAL,
            avg_absolute_premium_pct REAL,
            max_absolute_premium_pct REAL,
            positive_days INTEGER,
            negative_days INTEGER,
            avg_nav REAL,
            avg_market_price REAL,
            premium_frequency REAL
        )
    """)
    for i, item in enumerate(top_n):
        cursor.execute("""
            INSERT INTO top_spread_ranking
            (rank, fund_code, fund_name, data_points, avg_premium_pct,
             max_premium_pct, min_premium_pct, avg_absolute_premium_pct,
             max_absolute_premium_pct, positive_days, negative_days,
             avg_nav, avg_market_price, premium_frequency)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            i + 1, item["fund_code"], item["fund_name"],
            item["data_points"], item["avg_premium_pct"],
            item["max_premium_pct"], item["min_premium_pct"],
            item["avg_absolute_premium_pct"], item["max_absolute_premium_pct"],
            item["positive_days"], item["negative_days"],
            item["avg_nav"], item["avg_market_price"],
            item["premium_frequency"],
        ))
    conn.commit()
    conn.close()
    return filepath


def print_top_n_report(top_n: list[dict]) -> None:
    """打印Top N价差LOF报告。"""
    print("\n" + "=" * 110)
    print(f"  TOP {len(top_n)} LOFs WITH LARGEST PREMIUM/DISCOUNT SPREAD")
    print("=" * 110)
    header = f"  {'Rank':<5} {'Code':<8} {'Name':<35} {'AvgSpread%':<12} {'MaxSpread%':<12} " \
             f"{'MinSpread%':<12} {'PosDays':<8} {'NegDays':<8} {'Freq%':<8}"
    print(header)
    print("-" * 110)

    for i, item in enumerate(top_n):
        print(f"  {i+1:<5} {item['fund_code']:<8} {item['fund_name']:<35} "
              f"{item['avg_absolute_premium_pct']:<12.4f} {item['max_absolute_premium_pct']:<12.4f} "
              f"{item['min_premium_pct']:<12.4f} {item['positive_days']:<8} {item['negative_days']:<8} "
              f"{item['premium_frequency']:<8.2f}")

    print("-" * 110)
    print(f"  Legend: AvgSpread=平均绝对溢价率%, MaxSpread=最大溢价率%, "
          f"PosDays=溢价交易日数, NegDays=折价交易日数, Freq=溢价频率%")
    print("=" * 110)


# ===========================================================================
# CLI Entry Point
# ===========================================================================

def main(argv: Optional[list[str]] = None) -> int:
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

    parser = argparse.ArgumentParser(
        description="LOF全量数据采集与价差分析系统",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
用法:
  python -m fund_estimator.lof_crawler --discover
  python -m fund_estimator.lof_crawler --update-details
  python -m fund_estimator.lof_crawler --crawl-single 160223
  python -m fund_estimator.lof_crawler --crawl-all
  python -m fund_estimator.lof_crawler --spread-analysis --top 100
  python -m fund_estimator.lof_crawler --full-pipeline
        """,
    )

    parser.add_argument("--discover", action="store_true",
                        help="Phase 1: 发现LOF并创建主数据库")
    parser.add_argument("--update-details", action="store_true",
                        help="Phase 1b: 更新LOF详细信息")
    parser.add_argument("--crawl-single", type=str, default=None,
                        help="Phase 2: 抓取单个LOF历史数据")
    parser.add_argument("--crawl-all", action="store_true",
                        help="Phase 2: 批量抓取所有LOF历史数据")
    parser.add_argument("--spread-analysis", action="store_true",
                        help="Phase 3: 计算价差统计")
    parser.add_argument("--top", type=int, default=100,
                        help="Phase 4: 输出Top N结果 (default: 100)")
    parser.add_argument("--full-pipeline", action="store_true",
                        help="完整流程: discover + crawl-all + spread-analysis")
    parser.add_argument("--db-path", type=str, default=None,
                        help="SQLite数据库路径")

    args = parser.parse_args(argv)

    if args.db_path:
        global DB_PATH, DB_DIR
        DB_PATH = args.db_path
        DB_DIR = os.path.dirname(DB_PATH)
    os.makedirs(DB_DIR, exist_ok=True)

    if args.full_pipeline:
        print("=" * 60)
        print("  LOF全量数据采集与价差分析 - 完整流程")
        print("=" * 60)

        print("\n[Phase 1] 发现LOF并创建主数据库...")
        print("  Fetching fund list from Tiantian...")
        fund_list = fetch_fund_list()
        print(f"  Total funds: {len(fund_list)}")

        print("  Filtering tradable A-share LOFs...")
        lof_list = filter_tradable_lofs(fund_list)
        print(f"  Found {len(lof_list)} tradable LOFs")

        print("  Creating master database...")
        create_master_db(lof_list)

        print("  Updating fund details...")
        update_master_db_with_details()

        print("\n[Phase 2] 批量抓取LOF历史数据...")
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT fund_code FROM master_lof")
        lof_codes = [row[0] for row in cursor.fetchall()]
        conn.close()
        print(f"  Found {len(lof_codes)} LOFs in master database")

        results = crawl_all_fund_histories(lof_codes)
        success = sum(1 for r in results.values() if r.get("success"))
        with_prices = sum(1 for r in results.values() if r.get("price_count", 0) > 0)
        print(f"  History crawl complete: {success}/{len(lof_codes)} funds, "
              f"{with_prices} with market price data")

        print("\n[Phase 3-4] 价差分析与报告...")
        top_n = get_top_n_spread(args.top)
        filepath = save_top_n_results(top_n)
        print_top_n_report(top_n)

        print(f"\n  Database: {DB_PATH}")
        print(f"  Results:  {filepath}")
        return 0

    if args.discover:
        print("[Phase 1] 发现LOF并创建主数据库...")
        fund_list = fetch_fund_list()
        print(f"  Total funds: {len(fund_list)}")
        lof_list = filter_tradable_lofs(fund_list)
        print(f"  Found {len(lof_list)} tradable LOFs")
        create_master_db(lof_list)
        return 0

    if args.update_details:
        print("[Phase 1b] 更新LOF详细信息...")
        update_master_db_with_details()
        return 0

    if args.crawl_single:
        print(f"[Phase 2] 抓取 {args.crawl_single} 历史数据...")
        result = crawl_fund_history(args.crawl_single)
        print(f"  Result: {result}")
        return 0

    if args.crawl_all:
        print("[Phase 2] 批量抓取所有LOF历史数据...")
        conn = sqlite3.connect(DB_PATH)
        cursor = conn.cursor()
        cursor.execute("SELECT fund_code FROM master_lof")
        lof_codes = [row[0] for row in cursor.fetchall()]
        conn.close()
        print(f"  Found {len(lof_codes)} LOFs")
        results = crawl_all_fund_histories(lof_codes)
        success = sum(1 for r in results.values() if r.get("success"))
        print(f"  Complete: {success}/{len(lof_codes)} funds")
        return 0

    if args.spread_analysis:
        print("[Phase 3-4] 价差分析与报告...")
        top_n = get_top_n_spread(args.top)
        filepath = save_top_n_results(top_n)
        print_top_n_report(top_n)
        return 0

    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
