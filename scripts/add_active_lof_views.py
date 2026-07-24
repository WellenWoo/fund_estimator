"""在 lof_info.db 中创建辅助视图和索引，方便查询活跃 LOF"""
import sqlite3

db = r"E:\api\fund_estimator\lof_database\lof_info.db"
conn = sqlite3.connect(db)
cur = conn.cursor()

# 创建索引
print("创建索引...")
cur.execute("CREATE INDEX IF NOT EXISTS idx_active_lofs_code ON active_lofs(fund_code)")
cur.execute("CREATE INDEX IF NOT EXISTS idx_active_lofs_name ON active_lofs(fund_name)")

# 创建活跃度评级视图
print("""
CREATE VIEW v_active_lof_activity AS
SELECT
    fund_code,
    fund_name,
    activity_stats,
    CAST(replace(replace(activity_stats, '{"window_days":', ''), ',"max_consecutive_zero"', ',') AS REAL) as dummy
FROM active_lofs
""")

# 更实用的：创建一个简单的活跃度总结视图
cur.execute("""
DROP VIEW IF EXISTS v_active_lof_summary
""")
cur.execute("""
CREATE VIEW v_active_lof_summary AS
SELECT
    a.fund_code,
    a.fund_name,
    a.fund_type,
    a.is_passive,
    json_extract(a.activity_stats, '$.avg_vol') as avg_daily_volume,
    json_extract(a.activity_stats, '$.activity_ratio') as activity_ratio,
    json_extract(a.activity_stats, '$.latest_date') as latest_trade_date,
    CASE
        WHEN json_extract(a.activity_stats, '$.avg_vol') >= 100000 THEN '高活跃'
        WHEN json_extract(a.activity_stats, '$.avg_vol') >= 50000 THEN '中等活跃'
        ELSE '低活跃(但达标)'
    END as liquidity_level
FROM active_lofs a
ORDER BY json_extract(a.activity_stats, '$.avg_vol') DESC
""")

# 排除的基金列表视图
cur.execute("""
DROP VIEW IF EXISTS v_excluded_lofs
""")
cur.execute("""
CREATE VIEW v_excluded_lofs AS
SELECT
    m.fund_code,
    m.fund_name,
    m.fund_type,
    '未出现在active_lofs中' as reason
FROM master_lof m
WHERE m.fund_code NOT IN (SELECT fund_code FROM active_lofs)
ORDER BY m.fund_code
""")

conn.commit()

# 查询示例
print("\n=== 活跃度评级 ===")
for row in cur.execute("SELECT * FROM v_active_lof_summary LIMIT 5"):
    print(row)

print("\n=== 最低活跃度（但仍达标）的前5只 ===")
for row in cur.execute("SELECT * FROM v_active_lof_summary ORDER BY avg_daily_volume ASC LIMIT 5"):
    print(row)

print("\n=== 被排除的基金数量 ===")
print(cur.execute("SELECT COUNT(*) FROM v_excluded_lofs").fetchone())

print("\n=== 按 fund_type 统计活跃基金数量 ===")
for row in cur.execute("""
    SELECT a.fund_type, COUNT(*) as cnt
    FROM active_lofs a
    WHERE a.fund_type IS NOT NULL AND a.fund_type != ''
    GROUP BY a.fund_type
    ORDER BY cnt DESC
    LIMIT 10
"""):
    print(row)

conn.close()
print("\n[OK] 视图和索引已创建")
