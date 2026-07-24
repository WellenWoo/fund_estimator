import sqlite3

db = r"E:\api\fund_estimator\lof_database\lof_info.db"
conn = sqlite3.connect(db)
cur = conn.cursor()

# 表结构
cur.execute("PRAGMA table_info(master_lof)")
print("=== master_lof 字段 ===")
for row in cur.fetchall():
    print(row)

print()
cur.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='master_lof'")
print("DDL:")
print(cur.fetchone()[0])

print()
cur.execute("SELECT COUNT(*) FROM master_lof")
print("总记录数:", cur.fetchone()[0])

print()
cur.execute("SELECT * FROM master_lof LIMIT 2")
cols = [d[0] for d in cur.description]
print("列名:", cols)
for row in cur.fetchall():
    print(row)

conn.close()
