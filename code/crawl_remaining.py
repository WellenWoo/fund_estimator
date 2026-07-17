import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fund_estimator.lof_crawler.main import crawl_fund_history, DB_PATH, DB_DIR

# Funds that were not fully crawled
remaining = ["160120", "161006", "161021", "161218", "161220", "161660", "162606", "163408", "163416"]

for fund_code in remaining:
    print(f"Crawling {fund_code}...")
    try:
        result = crawl_fund_history(fund_code)
        print(f"  Result: {result}")
    except Exception as e:
        print(f"  Error: {e}")

print("\nAll remaining funds processed.")
