import urllib.request
import re
from datetime import date as Date

fund_code = '160211'
url = f'https://fund.eastmoney.com/pingzhongdata/{fund_code}.js?v={Date.today().isoformat()}'
req = urllib.request.Request(url, headers={'Referer': 'https://fund.eastmoney.com/'})
try:
    with urllib.request.urlopen(req, timeout=10) as resp:
        raw = resp.read().decode('utf-8', errors='ignore')
    
    m = re.search(r'Data_assetAllocation\s*=\s*([^;]+);', raw)
    if m:
        print('Data_assetAllocation:', m.group(1)[:500])
    
    m = re.search(r'Data_grandTotal\s*=\s*([^;]+);', raw)
    if m:
        print('Data_grandTotal:', m.group(1)[:500])
        
except Exception as e:
    print('error:', e)
