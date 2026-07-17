# LOF全量数据采集与价差分析系统

## 概述

本系统从天天基金、东方财富、新浪财经、腾讯财经等平台爬取数据，构建完整的LOF基金数据库，并分析场内/场外价差。

## 架构

```
lof_database/
├── lof_master.db              # SQLite主数据库
│   ├── master_lof             # LOF基本信息表 (271只)
│   ├── lof_detail_{code}      # 每只LOF独立数据表
│   └── top_spread_ranking     # Top N价差排名表
└── top_spread_lofs.json       # Top N价差结果(JSON)
```

## 数据库结构

### master_lof - LOF基本信息表
| 字段 | 类型 | 说明 |
|------|------|------|
| fund_code | TEXT PK | 基金代码(6位) |
| fund_name | TEXT | 基金名称 |
| fund_type | TEXT | 基金类型 |
| full_name | TEXT | 完整名称 |
| pinyin | TEXT | 拼音缩写 |
| share_class | TEXT | 份额类别(A/BASE) |
| is_index_fund | INTEGER | 是否指数型(0/1) |
| tracker_index | TEXT | 跟踪指数名称 |
| tracker_index_code | TEXT | 跟踪指数代码 |

### lof_detail_{code} - 每只LOF独立数据表
| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER PK | 自增主键 |
| fund_code | TEXT | 基金代码 |
| date | TEXT | 日期(YYYY-MM-DD) |
| nav | REAL | 单位净值 |
| acc_nav | REAL | 累计净值 |
| change_pct | REAL | 日增长率(%) |
| market_price | REAL | 场内成交价 |
| premium_discount | REAL | 溢价折价率(%) |
| volume | REAL | 成交量 |
| amount | REAL | 成交额 |

## 数据源

| 平台 | 用途 | API |
|------|------|-----|
| 天天基金 | 全量基金列表 | `fundcode_search.js` |
| 东方财富 | 历史净值 | `lsjz` API |
| 东方财富 | 基金详情 | `pingzhongdata.js` |
| 新浪财经 | 历史成交价 | K线API |
| 腾讯财经 | 实时行情(备用) | `qt.gtimg.cn` |

## 筛选规则

**保留:**
- 名称包含"LOF"
- A类份额或无后缀基础份额
- 股票型/混合型/指数型基金

**排除:**
- C/D/E/B/I/Y/R份额类
- FOF-LOF
- QDII-LOF
- 债券型/货币型LOF

## 使用方法

```bash
cd E:/api/fund_estimator/code

# Phase 1: 发现LOF并创建主数据库
python -m fund_estimator.lof_crawler --discover

# Phase 1b: 更新基金详细信息
python -m fund_estimator.lof_crawler --update-details

# Phase 2: 抓取单个LOF历史数据
python -m fund_estimator.lof_crawler --crawl-single 160223

# Phase 2: 批量抓取所有LOF历史数据
python -m fund_estimator.lof_crawler --crawl-all

# Phase 3-4: 价差分析与报告
python -m fund_estimator.lof_crawler --spread-analysis --top 100

# 完整流程
python -m fund_estimator.lof_crawler --full-pipeline
```

## 价差分析指标

| 指标 | 说明 |
|------|------|
| avg_absolute_premium_pct | 平均绝对溢价率(%) |
| max_absolute_premium_pct | 最大绝对溢价率(%) |
| min_premium_pct | 最小溢价率(%) |
| positive_days | 溢价交易日数 |
| negative_days | 折价交易日数 |
| premium_frequency | 溢价频率(%) |

溢价率 = (市场价 - 净值) / 净值 × 100%

## 技术细节

- 日期范围: 近5年 (2021-01-01 ~ 2026-12-31)
- 翻页策略: 每页20条, 间隔0.2-0.4s
- 批量限速: 每10只基金休眠1-2s
- 交易所前缀: 16xxxx→sz, 50xxxx→sh, 其他→sh
