# fund_estimator

基金实时估值程序 — 不是直接抄基金公司的"估算净值"，而是**用持仓 + 实时行情自己算**。

## 目标场景
- 主样本：国泰创业板指数(LOF)A，代码 `160223`
- 扩展：其他 LOF、ETF、主动管理基金

## 系统结构
```
fund_estimator/
├── core/                      # 核心模型
│   ├── holding.py              # FundHolding / StockPosition 数据类
│   ├── nav.py                  # NAV 净值与估算
│   └── portfolio.py            # Portfolio 组合聚合
├── data_sources/               # 数据获取层（多源容错）
│   ├── eastmoney/             # 东方财富：持仓、历史净值、股票仓位测算
│   ├── sina/                   # 新浪：实时行情（场内），GBK 编码
│   ├── tencent/                # 腾讯：实时行情（场内），GBK 编码
│   └── tiantian/              # 天天基金：估算净值（仅做参考校验）
├── estimators/                 # 估值算法
│   ├── holdings_based.py       # 持仓还原法（主推）
│   ├── index_proxy.py          # 参考指数法（备选 1）
│   └── hybrid.py               # 混合（备选 2）
├── backtest/                   # 验证循环
│   ├── daily_close.py          # 每日收盘回测
│   └── compare.py              # 与官方净值对比
├── tests/                      # 单元测试
├── scripts/                    # CLI 入口
└── configs/                    # 配置文件
```

## 算法主线（迭代顺序）
1. **v1 持仓还原法** — 用最新季报披露的前 10 大持仓 + 实时行情，估算净值
   - 只覆盖前 10 大持仓，约占股票仓位 30-50%；其余仓位用行业 ETF 或宽基指数代理
2. **v2 现金拖累修正** — 把股票仓位（Data_fundSharesPositions 拿到的 95%）、未投资现金、应计利息纳入
3. **v3 增量数据** — 用沪深 300 / 中证 500 / 创业板指 等指数实时点位插值补齐"未披露个股"的收益
4. **v4 ML 残差修正** — 用 XGBoost 修正历史系统性偏差
5. **v5 申赎份额修正** — 根据披露的申赎确认份额调整分母

## 验收标准
每个版本都要做：
- 每日 15:00 估算收盘净值
- 拉取基金公司公布的 T-1 净值（下午 21:00 后公布）
- 计算绝对误差 = |estimate - official| / official
- 平均绝对误差 < 0.5% 才算合格；< 0.3% 是优秀
