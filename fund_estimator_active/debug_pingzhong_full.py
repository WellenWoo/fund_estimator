import urllib.request
import re
from datetime import date as Date

fund_code = '160211'
url = f'https://fund.eastmoney.com/pingzhongdata/{fund_code}.js?v={Date.today().isoformat()}'
req = urllib.request.Request(url, headers={'Referer': 'https://fund.eastmoney.com/'})
try:
    with urllib.request.urlopen(req, timeout=10) as resp:
        raw = resp.read().decode('utf-8', errors='ignore')
    
    vars_list = re.findall(r'var\s+(\w+)\s*=', raw)
    print('All variables:', vars_list)
    
    for var in vars_list[:20]:
        m = re.search(rf'var\s+{var}\s*=\s*([^;]+);', raw)
        if m:
            val = m.group(1).strip()
            if len(val) < 200:
                print(f'{var}: {val}')
            else:
                print(f'{var}: {len(val)} chars')
                
except Exception as e:
    print('error:', e)
