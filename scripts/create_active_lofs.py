"""从 master_lof 中筛选交易活跃的 LOF 基金，创建 active_lofs 表。

筛选标准：
1. 最近 30 个交易日内无连续 5 日以上零成交
2. 最近 30 个交易日平均日成交量 > 10,000 份
3. 最近 30 个交易日至少 70% 的交易日有成交（成交量 > 0）

数据来源：新浪财经 K 线接口（带本地 CSV 缓存）
"""

from __future__ import annotations

import os
import sys
import time
import sqlite3

# 添加 code 到路径以便导入项目模块
sys.path.insert(0, r"E:\api\fund_estimator\code")

from fund_estimator.data_sources.sina.history import fetch_kline

# --------------------------------------------------------------------------- #
# 参数配置
# --------------------------------------------------------------------------- #
DB_PATH = r"E:\api\fund_estimator\lof_database\lof_info.db"
WINDOW_DAYS = 30          # 回看交易日数量
ZERO_STREAK_LIMIT = 5     # 连续零成交上限（超过则排除）
AVG_VOL_THRESHOLD = 10000 # 日均成交量阈值（份）
ACTIVITY_RATIO_THRESHOLD = 0.7  # 有成交交易日占比下限


def get_code_prefix(fund_code: str) -> str:
    """根据基金代码判断新浪 symbol 前缀。

    5 开头 → sh, 1/6/9 开头 → sz, 其他默认 sz
    """
    if fund_code.startswith("5"):
        return "sh"
    elif fund_code.startswith(("1", "6", "9")):
        return "sz"
    else:
        return "sz"


def analyze_volume(symbol: str) -> dict | None:
    """分析某 LOF 的成交量活跃度，返回分析结果或 None（如果获取失败）。"""
    try:
        rows = fetch_kline(symbol, datalen=WINDOW_DAYS + 10)
    except Exception as e:
        print(f"  [WARN] 获取 {symbol} 数据失败: {e}")
        return None

    if not rows:
        return None

    # 取最近 WINDOW_DAYS 条
    recent = rows[-WINDOW_DAYS:]
    volumes = [float(r["volume"]) for r in recent]

    total_days = len(volumes)
    nonzero_days = sum(1 for v in volumes if v > 0)
    zero_days = total_days - nonzero_days
    avg_vol = sum(volumes) / total_days if total_days else 0
    max_vol = max(volumes) if volumes else 0
    min_nonzero_vol = min((v for v in volumes if v > 0), default=0)

    # 计算最大连续零成交天数
    max_consecutive_zero = 0
    current_streak = 0
    for v in volumes:
        if v == 0:
            current_streak += 1
            max_consecutive_zero = max(max_consecutive_zero, current_streak)
        else:
            current_streak = 0

    activity_ratio = nonzero_days / total_days if total_days else 0

    return {
        "total_days": total_days,
        "nonzero_days": nonzero_days,
        "zero_days": zero_days,
        "avg_vol": avg_vol,
        "max_vol": max_vol,
        "min_nonzero_vol": min_nonzero_vol,
        "max_consecutive_zero": max_consecutive_zero,
        "activity_ratio": activity_ratio,
        "latest_date": recent[-1]["date"] if recent else "",
    }


def is_active(metrics: dict) -> bool:
    """判断是否满足活跃条件。"""
    if metrics["max_consecutive_zero"] >= ZERO_STREAK_LIMIT:
        return False
    if metrics["avg_vol"] < AVG_VOL_THRESHOLD:
        return False
    if metrics["activity_ratio"] < ACTIVITY_RATIO_THRESHOLD:
        return False
    return True


def create_active_lofs_table(conn: sqlite3.Connection) -> None:
    """创建 active_lofs 表（结构与 master_lof 完全一致）。"""
    cur = conn.cursor()

    # 删除旧表（如果有）
    cur.execute("DROP TABLE IF EXISTS active_lofs")

    # 复制 master_lof 结构
    cur.execute("""
        CREATE TABLE active_lofs (
            fund_code TEXT PRIMARY KEY,
            fund_name TEXT NOT NULL,
            fund_type TEXT,
            full_name TEXT,
            pinyin TEXT,
            share_class TEXT DEFAULT 'A',
            is_index_fund INTEGER DEFAULT 0,
            tracker_index TEXT DEFAULT '',
            tracker_index_code TEXT DEFAULT '',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            is_passive INTEGER DEFAULT 0
        )
    """)

    # 添加注释列，记录活跃度信息
    cur.execute("""
        ALTER TABLE active_lofs ADD COLUMN activity_stats TEXT
    """)
    cur.execute("""
        ALTER TABLE active_lofs ADD COLUMN last_updated TEXT DEFAULT CURRENT_TIMESTAMP
    """)

    print("[OK] 已创建 active_lofs 表（与 master_lof 字段一致）")


def main():
    print("=" * 60)
    print("LOF 活跃基金筛选工具")
    print("=" * 60)
    print()
    print(f"数据库: {DB_PATH}")
    print(f"回看窗口: 最近 {WINDOW_DAYS} 个交易日")
    print(f"筛选条件:")
    print(f"  - 最大连续零成交 < {ZERO_STREAK_LIMIT} 天")
    print(f"  - 日均成交量 > {AVG_VOL_THRESHOLD:,} 份")
    print(f"  - 有成交交易日占比 ≥ {ACTIVITY_RATIO_THRESHOLD:.0%}")
    print()

    # 读取 master_lof
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT fund_code, fund_name FROM master_lof ORDER BY fund_code")
    all_funds = cur.fetchall()
    print(f"master_lof 共有 {len(all_funds)} 只 LOF 基金")
    print()

    active_funds = []
    inactive_funds = []

    for i, (fund_code, fund_name) in enumerate(all_funds, 1):
        symbol = f"{get_code_prefix(fund_code)}{fund_code}"
        print(f"[{i}/{len(all_funds)}] 分析 {fund_code} {fund_name}...", end=" ")

        metrics = analyze_volume(symbol)
        if metrics is None:
            print("跳过（无法获取数据）")
            inactive_funds.append((fund_code, fund_name, "data_unavailable"))
            continue

        status = "活跃" if is_active(metrics) else "不活跃"
        print(status)

        entry = {
            "fund_code": fund_code,
            "fund_name": fund_name,
            "metrics": metrics,
        }

        if is_active(metrics):
            active_funds.append(entry)
        else:
            reason_parts = []
            if metrics["max_consecutive_zero"] >= ZERO_STREAK_LIMIT:
                reason_parts.append(f"连续零成交{metrics['max_consecutive_zero']}天")
            if metrics["avg_vol"] < AVG_VOL_THRESHOLD:
                reason_parts.append(f"均量{metrics['avg_vol']:.0f}<{AVG_VOL_THRESHOLD:,}")
            if metrics["activity_ratio"] < ACTIVITY_RATIO_THRESHOLD:
                reason_parts.append(f"成交率{metrics['activity_ratio']:.0%}")
            inactive_funds.append((fund_code, fund_name, "、".join(reason_parts)))

        # 避免请求过快，加小延迟
        time.sleep(0.1)

    # 创建新表并插入数据
    print()
    print("-" * 60)
    create_active_lofs_table(conn)

    cur = conn.cursor()
    import json

    for entry in active_funds:
        metrics = entry["metrics"]
        stats_json = json.dumps({
            "window_days": WINDOW_DAYS,
            "max_consecutive_zero": metrics["max_consecutive_zero"],
            "avg_vol": round(metrics["avg_vol"], 0),
            "max_vol": metrics["max_vol"],
            "activity_ratio": round(metrics["activity_ratio"], 4),
            "latest_date": metrics["latest_date"],
        }, ensure_ascii=False)

        cur.execute("""
            INSERT INTO active_lofs (
                fund_code, fund_name, fund_type, full_name, pinyin,
                share_class, is_index_fund, tracker_index, tracker_index_code,
                is_passive, activity_stats, last_updated
            )
            SELECT
                fund_code, fund_name, fund_type, full_name, pinyin,
                share_class, is_index_fund, tracker_index, tracker_index_code,
                is_passive, ?, datetime('now')
            FROM master_lof
            WHERE fund_code = ?
        """, (stats_json, entry["fund_code"]))

    conn.commit()

    print()
    print("=" * 60)
    print("结果汇总")
    print("=" * 60)
    print(f"总基金数: {len(all_funds)}")
    print(f"活跃基金: {len(active_funds)}")
    print(f"不活跃/剔除: {len(inactive_funds)}")
    print()

    if inactive_funds:
        print("剔除原因统计:")
        reason_counts = {}
        for _, _, reason in inactive_funds:
            # 拆分多个原因
            for r in reason.split("、"):
                reason_counts[r] = reason_counts.get(r, 0) + 1
        for reason, count in sorted(reason_counts.items(), key=lambda x: -x[1]):
            print(f"  {reason}: {count} 只")

    print()
    print(f"活跃基金列表:")
    for entry in active_funds[:20]:
        m = entry["metrics"]
        print(f"  {entry['fund_code']} {entry['fund_name']}: "
              f"均量={m['avg_vol']:.0f}, 成交率={m['activity_ratio']:.0%}, "
              f"最大连续零成交={m['max_consecutive_zero']}天")
    if len(active_funds) > 20:
        print(f"  ... 还有 {len(active_funds) - 20} 只")

    print()
    print(f"详情表已写入 active_lofs，可在 {DB_PATH} 中查询")

    conn.close()


if __name__ == "__main__":
    main()
