"""验证 active_lofs 表创建结果"""
import sqlite3, json

db = r"E:\api\fund_estimator\lof_database\lof_info.db"
conn = sqlite3.connect(db)
cur = conn.cursor()

# 表结构
print("=== active_lofs schema ===")
cur.execute("PRAGMA table_info(active_lofs)")
for row in cur.fetchall():
    print(row)

print()
cur.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='active_lofs'")
print(cur.fetchone()[0])

print()
# 数量对比
cur.execute("SELECT COUNT(*) FROM master_lof")
master_count = cur.fetchone()[0]
cur.execute("SELECT COUNT(*) FROM active_lofs")
active_count = cur.fetchone()[0]
print(f"master_lof: {master_count} 只")
print(f"active_lofs: {active_count} 只")
print(f"剔除: {master_count - active_count} 只")
print()

# 查看活跃基金成交量分布
print("=== 活跃基金成交量统计 ===")
cur.execute("SELECT activity_stats FROM active_lofs")
stats = []
for (s,) in cur.fetchall():
    if s:
        stats.append(json.loads(s))

if stats:
    avgs = [s["avg_vol"] for s in stats]
    ratios = [s["activity_ratio"] for s in stats]
    print(f"  最低均量: {min(avgs):,.0f}")
    print(f"  最高均量: {max(avgs):,.0f}")
    print(f"  平均均量: {sum(avgs)/len(avgs):,.0f}")
    print(f"  最低成交率: {min(ratios):.1%}")
    print(f"  最高成交率: {max(ratios):.1%}")
    print(f"  成交率100%的: {sum(1 for r in ratios if r == 1.0)}/{len(ratios)}")

# 抽样查看
print()
print("=== 前10只活跃基金示例 ===")
cur.execute("""
    SELECT fund_code, fund_name, activity_stats
    FROM active_lofs
    ORDER BY CAST(replace(activity_stats, '"avg_vol":', ',') AS REAL) DESC
    LIMIT 10
""")
# 上面SQL不可靠，改用Python排序
cur.execute("SELECT fund_code, fund_name, activity_stats FROM active_lofs")
rows = [(c, n, json.loads(s)) for c, n, s in cur.fetchall() if s]
rows.sort(key=lambda x: x[2]["avg_vol"], reverse=True)
for c, n, s in rows[:10]:
    print(f"  {c} {n}: 均量={s['avg_vol']:,.0f}, 成交率={s['activity_ratio']:.0%}")

# 后10只（最不活跃的活跃基金）
print()
print("=== 后10只活跃基金（最低成交量）===")
for c, n, s in rows[-10:]:
    print(f"  {c} {n}: 均量={s['avg_vol']:,.0f}, 成交率={s['activity_ratio']:.0%}")

conn.close()
