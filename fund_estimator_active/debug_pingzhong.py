import urllib.request
import re
from datetime import date as Date

fund_code = '160211'
url = f'https://fund.eastmoney.com/pingzhongdata/{fund_code}.js?v={Date.today().isoformat()}'
req = urllib.request.Request(url, headers={'Referer': 'https://fund.eastmoney.com/'})
try:
    with urllib.request.urlopen(req, timeout=10) as resp:
        raw = resp.read().decode('utf-8', errors='ignore')
    print('raw length:', len(raw))
    
    m = re.search(r'stockCodes\s*=\s*\[([^\]]+)\]', raw)
    if m:
        print('stockCodes found')
        print('stockCodes:', m.group(1)[:200])
    
    m = re.search(r'stockNames\s*=\s*\[([^\]]+)\]', raw)
    if m:
        print('stockNames found')
        print('stockNames:', m.group(1)[:200])
    
    m = re.search(r'stockPosition\s*=\s*\[([^\]]+)\]', raw)
    if m:
        print('stockPosition found')
        print('stockPosition:', m.group(1)[:300])
    
    m = re.search(r'stockNum\s*=\s*\[([^\]]+)\]', raw)
    if m:
        print('stockNum found')
        print('stockNum:', m.group(1)[:200])
    
    m = re.search(r'stockMarket\s*=\s*\[([^\]]+)\]', raw)
    if m:
        print('stockMarket found')
        print('stockMarket:', m.group(1)[:200])
        
except Exception as e:
    print('error:', e)
