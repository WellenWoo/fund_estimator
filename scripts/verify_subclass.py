import sqlite3

db = r"E:\api\fund_estimator\lof_database\lof_info.db"
conn = sqlite3.connect(db)
cur = conn.cursor()

# 字段对比
print("=== master_lof vs active_lofs ===")
master_cols = [r[1] for r in cur.execute("PRAGMA table_info(master_lof)").fetchall()]
active_cols = [r[1] for r in cur.execute("PRAGMA table_info(active_lofs)").fetchall()]
extra = set(active_cols) - set(master_cols)
print(f"master_lof cols: {master_cols}")
print(f"active_lofs cols: {active_cols}")
print(f"Extra in active_lofs: {extra if extra else 'none'}")

print()
print(f"master_lof count: {cur.execute('SELECT COUNT(*) FROM master_lof').fetchone()[0]}")
print(f"active_lofs count: {cur.execute('SELECT COUNT(*) FROM active_lofs').fetchone()[0]}")

# 检查active_lofs是否是master_lof子集
inactive_in_active = cur.execute(
    "SELECT fund_code FROM active_lofs WHERE fund_code NOT IN (SELECT fund_code FROM master_lof)"
).fetchall()
print(f"active_lofs中不在master_lof的记录: {len(inactive_in_active)}")

# 查看501087
print()
print("=== 501087 样例 ===")
for row in cur.execute('SELECT * FROM active_lofs WHERE fund_code="501087"'):
    print("active:", row)
for row in cur.execute('SELECT * FROM master_lof WHERE fund_code="501087"'):
    print("master:", row)

conn.close()
