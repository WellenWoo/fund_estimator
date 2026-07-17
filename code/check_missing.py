import sqlite3

conn = sqlite3.connect(r"E:\api\fund_estimator\lof_database\lof_master.db")
c = conn.cursor()
c.execute("SELECT fund_code FROM master_lof ORDER BY fund_code")
all_codes = [r[0] for r in c.fetchall()]
c.execute("SELECT name FROM sqlite_master WHERE type='table'")
tables = [r[0] for r in c.fetchall()]
dt = set()
for t in tables:
    if t.startswith("lof_detail_"):
        dt.add(t[len("lof_detail_"):])
missing = [code for code in all_codes if code not in dt]
print(f"Missing: {len(missing)}")
for m in missing:
    print(f"  {m}")
conn.close()
