import urllib.request
import re
from datetime import date as Date

fund_code = '160211'
url = f'https://fund.eastmoney.com/pingzhongdata/{fund_code}.js?v={Date.today().isoformat()}'
req = urllib.request.Request(url, headers={'Referer': 'https://fund.eastmoney.com/'})
try:
    with urllib.request.urlopen(req, timeout=10) as resp:
        raw = resp.read().decode('utf-8', errors='ignore')
    
    keywords = ['position', 'weight', 'pct', 'ratio', '持仓占比', '占净值', 'Data_stock', 'stockList', 'stockData', 'gpdm', 'gpjc', 'ccbl']
    for kw in keywords:
        idx = raw.lower().find(kw.lower())
        if idx != -1:
            print(f'{kw}: found at {idx}')
            print(f'  snippet: {raw[idx-20:idx+100]}')
        else:
            print(f'{kw}: NOT found')
            
except Exception as e:
    print('error:', e)
