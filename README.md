# LOF基金折价/溢价套利分析工具

一个用于分析LOF（上市型开放式基金）折价/溢价套利机会的Python工具包。

## 功能特性

- **多数据源**：支持从天天基金、新浪财经等获取基金数据
- **智能估值**：根据基金类型自动选择合适的净值估算算法
  - 主动型基金：前十大重仓股模拟法
  - 指数型基金：指数实时映射法
  - ETF联接基金：底仓ETF实时价格法
- **套利分析**：计算折溢价率、估算套利成本、生成套利信号
- **风险评估**：流动性风险、估值误差风险、时间差风险评估
- **多种输出**：支持文本、JSON、HTML三种报告格式
- **监控模式**：支持持续监控，发现套利机会自动提醒

## 项目结构

```
lof-arbitrage-tool/
├── main.py                    # 主入口程序
├── config/
│   └── config.yaml            # 配置文件
├── lof_arbitrage/             # 核心包
│   ├── __init__.py
│   ├── models.py              # 数据模型
│   ├── data_fetcher.py        # 数据获取模块
│   ├── nav_estimator.py       # 净值估算算法
│   ├── arbitrage_analyzer.py  # 套利分析模块
│   ├── core.py                # 核心调度
│   └── report.py              # 报告生成
└── output/                    # 输出目录（自动创建）
```

## 安装

### 依赖

- Python 3.7+
- requests（必需）
- PyYAML（可选，推荐）

```bash
pip install requests pyyaml
```

## 快速开始

### 方式一：使用默认配置

```bash
python main.py
```

### 方式二：指定基金代码

```bash
python main.py 501098 160119
```

### 方式三：使用自定义配置文件

```bash
python main.py -c my_config.yaml
```

### 方式四：指定输出格式

```bash
python main.py --format html
python main.py --format json
python main.py --format all    # 同时输出所有格式
```

### 方式五：持续监控模式

```bash
python main.py --monitor --interval 60
```

## Python API 用法

```python
from lof_arbitrage import run_analysis, FundAnalyzer

# 方式一：批量分析
result = run_analysis(["501098", "160119"])
print(result["summary"])

# 方式二：单只基金分析
analyzer = FundAnalyzer("501098")
analyzer.fetch_data()      # 获取数据
analyzer.estimate_nav()    # 估算净值
signal = analyzer.analyze()  # 套利分析
print(signal)

# 完整运行
result = analyzer.run()
print(result)
```

## 估值算法说明

| 算法 | 适用基金类型 | 精确度 | 说明 |
|------|-------------|--------|------|
| 前十大重仓股模拟法 | 主动型混合/股票基金 | 中（±1-2%） | 基于季报持仓+实时行情估算 |
| 行业ETF映射法 | 行业主题基金 | 中低 | 用行业ETF作为代理 |
| 指数实时映射法 | 指数型基金 | 高（<0.1%） | 直接用跟踪指数行情推算 |
| 底仓ETF实时价格法 | ETF联接基金 | 最高（<0.05%） | 用底层ETF的IOPV计算 |

## 套利成本估算

套利交易涉及以下成本（以持有>30天为例）：

| 成本项 | 费率（约） |
|--------|-----------|
| 申购费 | 0.12% - 1.5%（视平台折扣） |
| 赎回费 | 0.125% - 0.5%（视持有时间） |
| 场内佣金 | 0.025%（双向） |
| 印花税 | 0.05%（卖出） |
| 转托管费 | 约0.01% |
| **总成本** | **约0.45% - 2.0%** |

一般要求折溢价率超过 **1.5%-2%** 才具备套利价值。

## 风险提示

⚠️ **LOF套利并非无风险套利，存在以下风险：**

1. **时间差风险**：T日申购，T+2才能场内卖出，期间净值可能大幅波动
2. **流动性风险**：部分LOF基金场内成交清淡，大额进出困难
3. **估值偏差风险**：主动型基金估算净值与实际净值可能存在偏差
4. **申赎限制风险**：基金可能暂停大额申赎
5. **费率变动风险**：基金公司可能调整费率

**本工具仅供参考，不构成任何投资建议。请充分了解风险后审慎决策。**

## 配置说明

编辑 `config/config.yaml` 可自定义：

- `funds`: 监控的基金列表
- `arbitrage`: 套利触发阈值
- `output`: 输出格式和目录
- `data`: 数据获取参数
- `monitor`: 监控模式参数

## 数据来源

- 天天基金网 (eastmoney.com) - 基金档案、净值、持仓
- 新浪财经 (sina.com.cn) - 场内行情、股票实时行情
- 东方财富 (eastmoney.com) - 行情数据

## License

MIT
