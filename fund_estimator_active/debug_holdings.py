import urllib.request
import re
from datetime import datetime

fund_code = '160211'
url = f'https://fundf10.eastmoney.com/FundArchivesDatas.aspx?type=quarter&mode=0&code={fund_code}&rt={datetime.now().timestamp()}'
req = urllib.request.Request(url, headers={'Referer': f'https://fundf10.eastmoney.com/{fund_code}.html', 'User-Agent': 'Mozilla/5.0'})
try:
    with urllib.request.urlopen(req, timeout=15) as resp:
        raw = resp.read().decode('gbk', errors='ignore')
    print('raw length:', len(raw))
    print('first 1000 chars:', raw[:1000])
    periods = re.findall(r'var apidata\s*=\s*\{[^}]*?"(20\d{2}-\d{2}-\d{2})"', raw)
    print('periods:', periods)
    if not periods:
        m = re.search(r'var apidata\s*=\s*\[(.*?)\];\s*$', raw, re.S)
        print('alt match:', m is not None)
        if m:
            print('alt group 1 length:', len(m.group(1)))
            print('alt group 1:', m.group(1)[:500])
except Exception as e:
    print('error:', e)
