"""测试新浪K线接口对LOF基金的可用性"""
import sys, json
sys.path.insert(0, r"E:\api\fund_estimator\code")
from fund_estimator.data_sources.sina.history import fetch_kline

codes = [
    ("sh501001", "招商中证白酒LOF"),
    ("sz160223", "南方原油LOF"),
    ("sh501075", "华安黄金易ETF联接LOF"),
]

for code, name in codes:
    print(f"\n=== {code} {name} ===")
    try:
        rows = fetch_kline(code, datalen=10)
        print(f"记录数: {len(rows)}")
        if rows:
            for r in rows[-3:]:
                print(f"  {r['date']} vol={r['volume']:.0f} close={r['close']}")
            # 检查成交量分布
            vols = [r["volume"] for r in rows]
            zero_days = sum(1 for v in vols if v == 0)
            nonzero_days = sum(1 for v in vols if v > 0)
            avg_vol = sum(vols) / len(vols) if vols else 0
            print(f"  近10日: 零成交{zero_days}天, 非零{nonzero_days}天, 均量={avg_vol:.0f}")
        else:
            print("无数据")
    except Exception as e:
        print(f"错误: {e}")
