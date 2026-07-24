import urllib.request
import re
from datetime import date as Date

fund_code = '160211'
url = f'https://fundf10.eastmoney.com/ccmx_{fund_code}.html'
req = urllib.request.Request(url, headers={'Referer': 'https://fundf10.eastmoney.com/', 'User-Agent': 'Mozilla/5.0'})
try:
    with urllib.request.urlopen(req, timeout=10) as resp:
        raw = resp.read().decode('utf-8', errors='ignore')
    
    print('Length:', len(raw))
    
    m = re.search(r'<table.*?ccmxTable', raw)
    if m:
        print('ccmxTable found')
        table_start = m.start()
        table_end = raw.find('</table>', table_start)
        if table_end != -1:
            table_content = raw[table_start:table_end+8]
            print('Table snippet:', table_content[:1000])
            
    m = re.search(r'<td>600259</td>', raw)
    if m:
        print('Stock code found')
        print('Snippet:', raw[m.start()-50:m.start()+200])
        
except Exception as e:
    print('error:', e)
