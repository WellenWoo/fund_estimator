# -*- coding: utf-8 -*-
"""Final spread analysis on all available LOF data."""
import sys, os, json
sys.stdout.reconfigure(encoding='utf-8')
import sqlite3

DB_PATH = r"E:\api\fund_estimator\lof_database\lof_master.db"
DB_DIR = r"E:\api\fund_estimator\lof_database"

conn = sqlite3.connect(DB_PATH)
c = conn.cursor()

# Get all detail tables
c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'lof_detail_%'")
tables = [r[0] for r in c.fetchall()]
print(f"Detail tables: {len(tables)}")

stats = []
for tbl in tables:
    code = tbl.replace("lof_detail_", "")
    c.execute(f"""
        SELECT COUNT(*), AVG(premium_discount), MAX(ABS(premium_discount)),
               MIN(premium_discount), AVG(ABS(premium_discount)),
               SUM(CASE WHEN premium_discount > 0 THEN 1 ELSE 0 END),
               SUM(CASE WHEN premium_discount < 0 THEN 1 ELSE 0 END),
               AVG(nav), AVG(market_price)
        FROM {tbl} WHERE nav > 0 AND market_price > 0
    """)
    row = c.fetchone()
    if row and row[0] and row[0] >= 10:
        dp = row[0]
        c2 = conn.cursor()
        c2.execute("SELECT fund_name FROM master_lof WHERE fund_code=?", (code,))
        nr = c2.fetchone()
        fund_name = nr[0] if nr else code
        c2.close()
        
        avg_prem = row[1] or 0
        max_abs = row[2] or 0
        min_prem = row[3] or 0
        avg_abs = row[4] or 0
        pos = row[5] or 0
        neg = row[6] or 0
        avg_nav = row[7] or 0
        avg_mp = row[8] or 0
        
        stats.append({
            "fund_code": code, "fund_name": fund_name,
            "data_points": dp,
            "avg_premium_pct": round(avg_prem, 4),
            "max_premium_pct": round(max_abs, 4),
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

stats.sort(key=lambda x: x["avg_absolute_premium_pct"], reverse=True)
print(f"LOFs with spread data: {len(stats)}")

top_n = stats[:100]
filepath = os.path.join(DB_DIR, "top_spread_lofs.json")
with open(filepath, 'w', encoding='utf-8') as f:
    json.dump(top_n, f, ensure_ascii=False, indent=2)
print(f"Saved Top {len(top_n)} to {filepath}")

# Update SQLite ranking
conn = sqlite3.connect(DB_PATH)
c = conn.cursor()
c.execute("DROP TABLE IF EXISTS top_spread_ranking")
c.execute("""
    CREATE TABLE top_spread_ranking (
        rank INTEGER PRIMARY KEY, fund_code TEXT NOT NULL, fund_name TEXT NOT NULL,
        data_points INTEGER, avg_premium_pct REAL, max_premium_pct REAL,
        min_premium_pct REAL, avg_absolute_premium_pct REAL,
        max_absolute_premium_pct REAL, positive_days INTEGER, negative_days INTEGER,
        avg_nav REAL, avg_market_price REAL, premium_frequency REAL
    )
""")
for i, item in enumerate(top_n):
    c.execute("""
        INSERT INTO top_spread_ranking VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, (i+1, item["fund_code"], item["fund_name"], item["data_points"],
          item["avg_premium_pct"], item["max_premium_pct"], item["min_premium_pct"],
          item["avg_absolute_premium_pct"], item["max_absolute_premium_pct"],
          item["positive_days"], item["negative_days"],
          item["avg_nav"], item["avg_market_price"], item["premium_frequency"]))
conn.commit(); conn.close()

print(f"\n{'Rank':<5} {'Code':<8} {'Name':<35} {'AvgAbs%':<12} {'MaxAbs%':<12} {'Min%':<12} {'Pos':<6} {'Neg':<6} {'Freq%':<8}")
print("-" * 110)
for i, s in enumerate(top_n):
    print(f"  {i+1:<5} {s['fund_code']:<8} {s['fund_name']:<35} {s['avg_absolute_premium_pct']:<12.4f} {s['max_absolute_premium_pct']:<12.4f} {s['min_premium_pct']:<12.4f} {s['positive_days']:<6} {s['negative_days']:<6} {s['premium_frequency']:<8.2f}")

print(f"\nDatabase: {DB_PATH}")
print(f"Results:  {filepath}")
