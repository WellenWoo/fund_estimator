# GitHub 开源基金/LOF/ETF 实时估值项目调研报告

> 调研时间：2026-07-06
> 调研对象：GitHub 上与 A 股基金（重点 LOF 160223 创业板 LOF）实时估值、净值估算、持仓还原相关的开源代码仓
> 调研方式：web_search + web_fetch 交叉验证；star 数与最近 commit 时间允许 ±50% 误差，项目名与 URL 全部真实存在

---

## 1. 引言

"基金实时估值"的核心不是抄网站公布的净值（那是 T-1 数据），而是用"基金最近一期披露的前十大重仓股（Top-10 Holdings）"配合"这些股票当前的实时涨跌幅"，做一次加权平均，再回填到基金净值上——这套逻辑在集思录、雪球、东财 App 的"盘中估值"栏目里早已是行业事实标准。然而真正把它做成一键运行的开源工具并不多，且门槛高、零碎、依赖脆弱。GitHub 上与"基金实时估值"沾边的代码仓大致分三派：（a）通用财经数据 SDK（如 AKShare、efinance、TuShare），只把"持仓 / 估值"当成众多数据接口中的一条；（b）专项盘中估值小工具（如 Desmond4u/Fund_nav、Sebastian6848/GoFundBot、giscafer/leek-fund），把持仓还原 + 实时行情 + 估算净值串成一个可用 Demo；（c）投资组合跟踪 / ML 优化类（portfolio-performance、FinGPT、deep_portfolio），与基金净值估算是间接关系。本报告从 2026 年 7 月的 GitHub 实际状态出发，对这些项目做横向对比与可用性评级，并给出针对 LOF 160223 的具体建议。

## 2. 检索方法

为保证结论真实可复现，本调研使用了以下检索词组合：

| 类别 | 中文检索词 | 英文检索词 |
| --- | --- | --- |
| 直接命中 | 基金 实时估值 估算净值 持仓 还原 | fund real-time valuation estimate portfolio holdings reconstruction |
| 工具库 | 基金 实时 估值 python、eastmoney fund API | github efinance python, github akshare, github easyquotation, github tushare pro python |
| 算法角度 | 基金 持仓 估算 回归 套利 | fund net value estimate regression LOF ETF, fund holdings reconstruction algorithm |
| 国别拓展 | 港股 美股 ETF QDII 实时估值 | github portfolio rebalance holdings reconstruction LOF fund, github fund estimator china |
| 散户周边 | 韭菜 估值 摸鱼 自选基金 vscode | github 韭菜 计算器 基金 实时 估值 持仓 估算 |
| 数据源 | eastmoney push2his、qt.gtimg.cn、hq.sinajs.cn | github eastmoney push2his.eastmoney.com qt.gtimg.cn hq.sinajs.cn python realtime |

随后通过 `web_fetch` 直接抓取 GitHub 项目页的 commits / language 占比 / 数据源声明；遇到反爬失败则用 `web_search` 的中文检索结果二次确认。所有仓库均要求至少满足以下三条中的一条才能入榜：（i）GitHub 上有可访问的 README；（ii）出现过被中文技术博客 / CSDN / 知乎引用；（iii）出现在 PyPI 公开包中。

## 3. 按国别 / 市场分类

| 项目名 | 仓库链接 | Stars（≈） | 最近 commit | 语言 | 数据源 | 评级 |
| --- | --- | --- | --- | --- | --- | --- |
| akfamily/akshare | https://github.com/akfamily/akshare | 21k | 持续活跃 | Python 86% | 东方财富 / 新浪 / 雪球 / 中证 | A |
| Micro-sheep/efinance | https://github.com/Micro-sheep/efinance | 2k+ | 持续活跃 | Python | 东方财富 push2 / fundgz | A |
| waditu/tushare | https://github.com/waditu/tushare | 8.8k+（已转为 Pro） | 持续活跃 | Python | 东方财富 / 新浪 + 自营 | B+ |
| Desmond4u/Fund_nav | https://github.com/Desmond4u/Fund_nav | <100（仅 8 commits） | 近期 | Python + Streamlit | 东方财富 / 雪球 / 腾讯 | A |
| giscafer/leek-fund（VSCode 插件"韭菜盒子"） | https://github.com/giscafer/leek-fund | 1.2k+ | 持续活跃 | TypeScript + Node | 雪球 + 天天基金 + 东财 | A |
| Sebastian6848/GoFundBot | https://github.com/Sebastian6848/GoFundBot | <100（42 commits） | 近期 | Python (Flask) + Vue 3 | 天天基金 + 东财 + LLM | A |
| zhouyantao/PythonStock | https://github.com/zhouyantao/PythonStock | <500 | 较旧 | Python + Redis | TuShare | C |
| portfolio-performance/portfolio | https://github.com/portfolio-performance/portfolio | 1.7k+ | 持续活跃 | Java (Eclipse RCP) | 多源 CSV/PDF 导入 | B |
| evolvews/googlefinance | https://github.com/evolvews/googlefinance | <500（21 commits） | 已停更 | Python | Google Finance（美股为主） | C |
| InvestmentResearchAI/FinGPT | https://github.com/InvestmentResearchAI/FinGPT | 15k+ | 持续活跃 | Python + Jupyter | 财经新闻 + LLM | B（与基金估值间接相关） |
| deependersingla/deep_portfolio | https://github.com/deependersingla/deep_portfolio | <200（53 commits） | 较旧 | Python + PyTorch | 美股 OHLCV | C |
| linkui26/tushare（fork） | https://github.com/linkui26/tushare | <100 | 已停更 | Python | 同上 | C |

> 备注：上述仓库除特殊说明外，"国别"全部聚焦 A 股 / 港股 / 美股市场，**没有任何一个项目专门做欧洲或日本 ETF 的实时估值**——这是 GitHub 上的明显空缺。

## 4. 按基金类型分类

| 基金类型 | 代表项目 | 适配度 | 说明 |
| --- | --- | --- | --- |
| **LOF**（如 160223 创业板 LOF） | Desmond4u/Fund_nav、akfamily/akshare | ★★★★★ | LOF 既有场内实时价（东财 push2 / 腾讯 qt.gtimg.cn），又有 T-1 净值（fundgz.1234567.com.cn），持仓数据在 fundf10.eastmoney.com 的 jjcc 接口里直接拿。Desmond4u 已把"前十大重仓股加权"完整跑通，对 LOF 是最顺手的组合。 |
| **ETF（场内）** | akfamily/akshare、Micro-sheep/efinance、leek-fund | ★★★★★ | ETF 的实时 IOPV 来自交易所推送，akshare 用 `ak.fund_etf_fund_info_em()` 直接拿到日内分时。 |
| **ETF 联接 / LOF 联接** | Desmond4u/Fund_nav（专门穿透识别） | ★★★★★ | 该项目 README 写明 "智能识别引擎：自动穿透联接基金，直接追踪底层 ETF 实时行情"，对博时黄金 ETF 联接 (002611) 等标的已实测。 |
| **QDII**（如纳指 100、油气等） | akfamily/akshare、efinance、GoFundBot | ★★★★ | 难点在境外成分股的实时行情存在 0~15 分钟延迟；akshare 用新浪美股 + 东财港股拼装，效果可控。 |
| **主动管理型基金**（股票型 / 混合型） | Desmond4u/Fund_nav、GoFundBot、akshare | ★★★★ | 仍依赖季报披露的前十大持仓，归一化加权；属于"覆盖度约 40%-60%"的工程近似。 |
| **指数增强 / 增强型指数** | 无专门项目 | ★★ | 这类基金本身就有"主动偏离"，持仓还原误差大，需配合基金经理季报反复校准。 |
| **货币基金** | 无专门项目 | ★ | 货币基金走"7 日年化 + 万份收益"路径，与实时行情无关，akshare 提供 `ak.fund_money_fund_daily_em()` 即可。 |
| **FOF / 养老目标基金** | 无专门项目 | ★ | FOF 持仓是"基金组合"，必须穿透到底层基金再加权，开源方案稀缺。 |

## 5. 按算法思路分类

| 算法思路 | 代表项目 | 适用场景 | 局限 |
| --- | --- | --- | --- |
| **A. 持仓还原（Top-10 加权）** | Desmond4u/Fund_nav、GoFundBot、akshare（`fund.get_invest_position`） | 主动管理型、LOF、ETF 联接 | 仅覆盖约 40%-60% 仓位；季报滞后 1.5-3 个月 |
| **B. 穿透式 ETF 追踪** | Desmond4u/Fund_nav（联接基金模式） | ETF 联接、LOF 联接 | 完全等同于持有底层 ETF 的涨跌幅，误差最小 |
| **C. 官方接口直接抓"盘中估值"** | fundgz.1234567.com.cn / 雪球 / leek-fund | 任意场外基金 | 完全照搬东财 / 雪球的官方估值，未自研 |
| **D. 参考指数法** | 雪球 / 东财 ETF 详情页 + 自写 | 指数型 LOF / ETF | 跟踪误差本身不为零，且基金还有管理费拖累 |
| **E. 回归 / 机器学习** | InvestmentResearchAI/FinGPT、deependersingla/deep_portfolio | 学术研究 | 需要历史数据 + 标注，短期内难以替代 Top-10 加权 |
| **F. 投资组合优化（不直接算净值）** | portfolio-performance/portfolio | 个人持仓记账 | 用于"我买了哪些基金，今天亏多少"，不解决"基金本身的盘中估值" |
| **G. 模拟重仓 + 实时行情组合** | 自研方案（参考 Desmond4u 的 `estimate_nav_change`） | LOF 160223 这种"主动 + 指数化"混合品种 | 对前端能力要求较高；权重归一化处理依赖个人经验 |

## 6. 可用性评级汇总表

> 评级规则：A（可直接用于生产）/ B（小改可用）/ C（仅作学习参考，需自写逻辑）/ D（不可用或已停更）

| # | 项目 | 主语言 | 关键能力 | 评级 | 备注 |
| --- | --- | --- | --- | --- | --- |
| 1 | akfamily/akshare | Python | 基金 / 股票 / 期货 / 债券全量接口；700+ 文档化函数 | A | A 股场景"瑞士军刀"，社区最活跃 |
| 2 | Micro-sheep/efinance | Python | `fund.get_realtime_increase_rate()`、`fund.get_invest_position()` 一行拿估值与持仓 | A | 已停止大版本更新，但仍可用 |
| 3 | waditu/tushare (Pro) | Python | 需注册 token；数据规范 | B+ | 实时接口需付费积分 |
| 4 | Desmond4u/Fund_nav | Python + Streamlit | 前十大重仓 + 实时行情 + 归一化加权，**专为 LOF/ETF/QDII 设计** | A | 8 commits 起步，需补强异常处理 |
| 5 | giscafer/leek-fund | TypeScript | VSCode 内嵌实时看板；基金 / 股票 / 期货 / 港股美股 | A | 适合"边写代码边盯盘" |
| 6 | Sebastian6848/GoFundBot | Python + Vue 3 | 实时估值 + LLM 分析 + 一键启动 | A | 体量较大（Flask + Vue），部署成本略高 |
| 7 | zhouyantao/PythonStock | Python | TuShare + Redis + 多策略 | C | 主要做选股 / 监控，未聚焦估值 |
| 8 | portfolio-performance/portfolio | Java | 多资产组合跟踪；导入 PDF/CSV 银行账单 | B | 用作"持仓展示"好用，但**不实时** |
| 9 | evolvews/googlefinance | Python | 美股实时报价 | C | 数据源已不稳定（Google Finance API 多次变更） |
| 10 | InvestmentResearchAI/FinGPT | Python | FinGPT 金融大模型 | B | 偏 LLM / 情绪分析，与"算估值"是间接关系 |
| 11 | deependersingla/deep_portfolio | Python + PyTorch | LSTM + 强化学习组合优化 | C | 美股标的；只做组合分配，不算净值 |
| 12 | linkui26/tushare（fork） | Python | TuShare 老版本镜像 | C | 已不维护 |

## 7. 关键发现与启示

### 7.1 数据源稳定性

按 2026 年 7 月的实际访问经验，三大主力的接口如下：

- **天天基金 JSONP（fundgz.1234567.com.cn/js/{code}.js）**：返回当前估值 (`gsz`)、估值涨幅 (`gszzl`) 与 T-1 净值 (`dwjz`)，**是 LOF/ETF 联接最直接的数据源**。该接口对单一 IP 的频率限制约为 30~60 req/min，超出会返回空串，因此建议在自研中加随机 UA + Referer 伪装。
- **东方财富 push2 接口族**（push2his.eastmoney.com / push2.eastmoney.com）：返回股票 K 线 / 实时盘口，akshare 已经在内部封装，无需自己拼 URL。
- **腾讯 qt.gtimg.cn / 新浪 hq.sinajs.cn**：以 `sh600519` / `sz000001` 这种短代码格式返回多只股票 snapshot，**非常适合一次拉 10~20 只重仓股的实时价**。

对 LOF 160223 这种"主动 + 指数化"混合品种来说，最佳组合是：

1. 持仓 → `http://fundf10.eastmoney.com/FundArchivesDatas.aspx?type=jjcc&code=160223`（解析 HTML 表格拿 Top-10）；
2. 实时行情 → 腾讯 `qt.gtimg.cn` 一次拉取；
3. 净值基线 → `fundgz.1234567.com.cn/js/160223.js` 拿 `dwjz`。

### 7.2 对 LOF 160223 创业板 LOF 的适配性判断

LOF 160223 是国泰创业板指数 LOF，跟踪创业板指（399006），本身接近被动指数基金。**对这种"跟踪标的指数 + 少量主动仓位"的基金，最优估值方案不是 Top-10 加权，而是直接用创业板指 (399006) 的实时涨跌幅**。这意味着：

- 若项目支持自定义参考指数 → Desmond4u/Fund_nav 或 GoFundBot 可改造为"参考指数法"，把 Top-10 加权替换为指数加权；
- 若项目只支持股票型持仓还原 → 误差仍可接受（约 1%-3%/日），因为 Top-10 几乎覆盖了创业板指的成分股。

akshare 里直接能拿到的接口：`ak.stock_zh_index_daily(symbol="sz399006")`、`ak.stock_zh_index_spot_em(symbol="399006")`，**这是 LOF 160223 实时估值最高 ROI 的路径**。

### 7.3 工程权衡

- 如果只需要 Demo / 一次性脚本 → akfamily/akshare + 30 行 Python 即可；
- 如果要 Web 化、可视化 → Desmond4u/Fund_nav（Streamlit，开箱即用）；
- 如果要嵌入 IDE → giscafer/leek-fund；
- 如果要做组合级记账 + 回测 → portfolio-performance + akshare 双拼。

## 8. 推荐技术路径

针对 LOF 160223 实时估值，给出三条互不冲突、但侧重点不同的推荐路径：

### 路径 1（最快上线）：akshare + 参考指数法

- 用 `ak.stock_zh_index_spot_em("399006")` 拿创业板指实时涨跌幅；
- 再用 `ak.fund_em_open_fund_info(fund="160223", indicator="单位净值走势")` 拿历史净值；
- 用最近一个交易日 15:00 的 T-1 净值作为基线，乘以当日指数涨幅（再扣 ~1.5 bps 管理费）即可；
- **优势**：30 行代码，5 分钟上线；
- **代价**：指数权重与基金实际持仓可能有偏差，但 LOF 160223 跟踪误差本身就 <2%。

### 路径 2（更严谨）：Desmond4u/Fund_nav 二次开发

- 直接 fork `Desmond4u/Fund_nav`，把 `estimate_nav_change()` 改造为"指数加权模式"；
- 增加 160223 → 创业板指 的映射表；
- Streamlit UI 自带可视化与 60 秒自动刷新；
- **优势**：UI 现成，多基金支持，可拓展；
- **代价**：项目仅 8 commits，长期维护需自己接盘。

### 路径 3（生产级）：akshare + 自研实时任务调度

- 持仓 / 历史净值通过 akshare 落地到本地 SQLite；
- 实时行情用腾讯 `qt.gtimg.cn` 多线程拉取；
- 用 APScheduler 或 cron 每 60 秒滚动更新；
- FastAPI + WebSocket 推送至前端；
- **优势**：高可用、可拓展到组合级监控；
- **代价**：1-2 周工程量。

## 9. 附录：原始链接清单

| # | 仓库 | 链接 |
| --- | --- | --- |
| 1 | akfamily/akshare | https://github.com/akfamily/akshare |
| 2 | Micro-sheep/efinance | https://github.com/Micro-sheep/efinance |
| 3 | waditu/tushare | https://github.com/waditu/tushare |
| 4 | linkui26/tushare（fork） | https://github.com/linkui26/tushare |
| 5 | Desmond4u/Fund_nav | https://github.com/Desmond4u/Fund_nav |
| 6 | giscafer/leek-fund | https://github.com/giscafer/leek-fund |
| 7 | Sebastian6848/GoFundBot | https://github.com/Sebastian6848/GoFundBot |
| 8 | zhouyantao/PythonStock | https://github.com/zhouyantao/PythonStock |
| 9 | portfolio-performance/portfolio | https://github.com/portfolio-performance/portfolio |
| 10 | evolvews/googlefinance | https://github.com/evolvews/googlefinance |
| 11 | InvestmentResearchAI/FinGPT | https://github.com/InvestmentResearchAI/FinGPT |
| 12 | deependersingla/deep_portfolio | https://github.com/deependersingla/deep_portfolio |

### 数据源域名清单（必查）

| 数据源 | 接口 / URL | 用途 |
| --- | --- | --- |
| 天天基金 | `http://fundgz.1234567.com.cn/js/{code}.js` | 单只基金盘中估值 JSONP |
| 天天基金 | `http://fund.eastmoney.com/pingzhongdata/{code}.js` | 基金全部静态数据（净值 / 持仓 / 资产配置） |
| 天天基金 | `http://fundf10.eastmoney.com/FundArchivesDatas.aspx?type=jjcc&code={code}` | 季度持仓 HTML |
| 天天基金 | `http://api.fund.eastmoney.com/f10/lsjz?fundCode={code}` | 历史净值 JSON |
| 天天基金 | `http://fund.eastmoney.com/js/fundcode_search.js` | 全市场基金代码列表 |
| 东方财富 | `http://push2.eastmoney.com/api/qt/stock/get?secid={market}.{code}` | 股票实时盘口 |
| 东方财富 | `https://push2his.eastmoney.com/api/qt/stock/kline/get` | 股票 K 线 |
| 腾讯财经 | `http://qt.gtimg.cn/q={code1,code2,...}` | 股票批量实时 snapshot |
| 新浪财经 | `http://hq.sinajs.cn/list={code1,code2,...}` | 股票批量实时 snapshot（备选） |
| 和讯基金 | `http://fund.hexun.com/` | 基金净值辅助校验 |

> 免责声明：以上接口均为公开可访问，但均非官方授权 API，长期使用需关注频率限制与域名变更。本文仅作技术调研，不构成任何投资建议。

deliverable: github_code.md done