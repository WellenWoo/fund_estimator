import urllib.request
import re
from datetime import date as Date

fund_code = '160211'
url = f'https://fund.eastmoney.com/pingzhongdata/{fund_code}.js?v={Date.today().isoformat()}'
req = urllib.request.Request(url, headers={'Referer': 'https://fund.eastmoney.com/'})
try:
    with urllib.request.urlopen(req, timeout=10) as resp:
        raw = resp.read().decode('utf-8', errors='ignore')
    
    keywords = ['stockCodes', 'stockNames', 'stockPosition', 'stockNum', 'stockMarket', 'Data_fundPortfolio', 'Data_recentFavoriate', 'fundSharesPositions']
    for kw in keywords:
        idx = raw.find(kw)
        if idx != -1:
            print(f'{kw}: found at {idx}')
            print(f'  snippet: {raw[idx:idx+200]}')
        else:
            print(f'{kw}: NOT found')
            
except Exception as e:
    print('error:', e)
