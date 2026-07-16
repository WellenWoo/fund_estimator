# fund_estimator_index_agent — 被动指数型基金实时估值 Agent

通用化的被动指数型基金实时估值引擎。用户只需输入**任意基金代码**（如 160223、159915、510300 等），Agent 自动完成基金信息查询、类型识别、估值算法选择和实时估值计算。

## 核心功能

### 1. 基金类型自动识别

Agent 自动查询基金基本信息并判断是否为**被动指数型基金**：

- **被动指数型**（指数型 / LOF / ETF） → 使用参考指数法
- **主动管理型**（股票型 / 混合型 / QDII） → 使用持仓还原法

判断依据综合 5 个信号：
1. `fund_type` 字段是否包含"指数型"
2. `fund_subtype` 是否包含"指数"/"LOF"/"ETF"
3. `fund_name` 是否包含"指数"/"ETF"/"LOF"
4. 是否有 `tracker_index`（跟踪指数）
5. 基金代码列表中的 type 字段（从天天基金全量列表获取）

### 2. 智能算法选择

| 基金类型 | 算法 | 精度 (MAE) | 适用场景 |
|---|---|---|---|
| 被动指数型 | `v_index_full_no_cash` | **0.11pp** | 指数型 LOF/ETF，跟踪误差极小 |
| 主动管理型（高覆盖） | `v_index_blend` | 0.40pp | 前十大持仓 >70% 的主动基金 |
| 主动管理型（低覆盖） | `v_top10` | 1.03pp | 持仓覆盖率低的主动基金 |

### 3. 多模式运行

- **单次估值**: `--fund <code> --date <date>`
- **批量估值**: `--fund <code> --batch --start <date> --end <date>`
- **交互模式**: `--interactive`

## 快速开始

### 单次估值

```bash
cd E:/api/fund_estimator/code
python -c "from fund_estimator.fund_estimator_index_agent import main; main(['--fund', '160223', '--date', '2026-07-13'])"
```

### 指定估值方法

```bash
python -c "from fund_estimator.fund_estimator_index_agent import main; main(['--fund', '160223', '--date', '2026-07-13', '--method', 'v_index_full_no_cash'])"
```

### 批量估值

```bash
python -c "from fund_estimator.fund_estimator_index_agent import main; main(['--fund', '160223', '--batch', '--start', '2026-07-01', '--end', '2026-07-13'])"
```

### 交互式模式

```bash
python -c "from fund_estimator.fund_estimator_index_agent import main; main(['--interactive'])"
```

交互模式下可用命令：
- `list` — 列出常用指数型基金
- `info <code>` — 查询基金基本信息
- `estimate <code> [date] [method]` — 单次估值
- `batch <code> <start> <end>` — 批量估值

## 项目结构

```
fund_estimator_index_agent/
├── __init__.py          # 主模块（全部逻辑）
├── __main__.py          # python -m 入口
└── README.md            # 本文档
```

## 数据源

| 数据源 | 用途 | 接口 |
|---|---|---|
| 天天基金 fundgz | 基金名称、盘中估值 | `fundgz.1234567.com.cn/js/{code}.js` |
| 天天基金 fundcode_search | 全市场基金代码列表（27000+） | `fund.eastmoney.com/js/fundcode_search.js` |
| 东方财富 pingzhongdata | 基金名称等附加信息 | `fund.eastmoney.com/pingzhongdata/{code}.js` |
| 东方财富基金档案 | 季报持仓 | `fundf10.eastmoney.com/FundArchivesDatas.aspx` |
| 东方财富历史净值 | T-1 NAV | `api.fund.eastmoney.com/f10/lsjz` |
| 新浪财经 | 实时行情 + 历史 K 线 | `hq.sinajs.cn` / `quotes.sina.cn` |
| 腾讯财经 | 备用实时行情 | `qt.gtimg.cn` |

## 估值算法

详见 `fund_estimator/estimators/holdings_based.py` 和 `ITERATIONS.md`。

核心算法 `v_index_full_no_cash` 在 53 个交易日的回测中表现最优：
- MAE: **0.1153 pp**（目标 <0.5pp，优于目标 4.3 倍）
- RMSE: 0.1413 pp
- Max error: 0.3633 pp
- 超阈值: 0/53（全部合格）

## 依赖

- Python 3.11+
- 仅使用标准库（`urllib`, `re`, `json`, `dataclasses`, `argparse`）
- 无第三方依赖
- 网络：能访问东方财富 / 新浪 / 天天基金

## 已知限制

1. 实时行情接口需要能访问国内网络
2. 季报持仓数据有 1.5-3 个月滞后
3. 非交易日自动跳过
4. 官方 NAV 通常在 21:00 后才公布
5. 基金名称/跟踪指数信息依赖东方财富 API，接口格式可能变化
