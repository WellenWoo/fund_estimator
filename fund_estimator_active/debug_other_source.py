import urllib.request
import json
import re
from datetime import date as Date

fund_code = '160211'

urls = [
    f'https://api.fund.eastmoney.com/f10/lsjz?fundCode={fund_code}&pageIndex=1&pageSize=20&sdate=&edate=',
    f'https://fund.eastmoney.com/{fund_code}.html',
    f'https://fundf10.eastmoney.com/ccmx_{fund_code}.html',
]

for url in urls:
    try:
        req = urllib.request.Request(url, headers={'Referer': 'https://fund.eastmoney.com/', 'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw = resp.read().decode('utf-8', errors='ignore')
        print(f'URL: {url}')
        print(f'Length: {len(raw)}')
        if len(raw) > 0:
            print(f'First 300 chars: {raw[:300]}')
        print('---')
    except Exception as e:
        print(f'URL: {url}')
        print(f'Error: {e}')
        print('---')
