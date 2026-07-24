"""
数据获取模块
============

负责从多个数据源获取基金信息、净值、持仓、场内行情等数据。
数据源包括：
    - 天天基金网 (eastmoney.com)
    - 新浪财经 (sina.com.cn)
    - 雪球 (xueqiu.com)
"""

import re
import json
import time
import random
from typing import List, Optional, Dict, Tuple
from urllib.parse import quote

try:
    import requests
except ImportError:
    requests = None

from .models import FundInfo, Holding


class DataFetcher:
    """基金数据获取器"""

    def __init__(self, timeout: int = 10):
        self.timeout = timeout
        self.session = None
        if requests:
            self.session = requests.Session()
            self.session.headers.update({
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
            })

    def _get(self, url: str, **kwargs) -> Optional[str]:
        """发送HTTP GET请求"""
        if not self.session:
            return None
        try:
            kwargs.setdefault("timeout", self.timeout)
            resp = self.session.get(url, **kwargs)
            resp.encoding = resp.apparent_encoding or "utf-8"
            if resp.status_code == 200:
                return resp.text
            return None
        except Exception:
            return None

    # ------------------- 基金基本信息 -------------------

    def fetch_fund_info(self, code: str) -> FundInfo:
        """
        获取基金基本信息
        优先从天天基金网获取
        """
        info = FundInfo(code=code, name=f"基金{code}")

        # 尝试从天天基金基金档案页获取
        html = self._get(f"https://fundf10.eastmoney.com/jbgk_{code}.html")
        if html:
            info = self._parse_fund_info_html(html, info)

        # 获取最新净值
        nav_data = self.fetch_latest_nav(code)
        if nav_data:
            info.last_nav = nav_data.get("nav", 0)
            info.last_nav_date = nav_data.get("date", "")
            info.last_nav_change = nav_data.get("change", 0)

        # 获取前一交易日净值
        prev_nav = self.fetch_prev_nav(code)
        if prev_nav:
            info.prev_nav = prev_nav

        # 获取持仓
        holdings = self.fetch_holdings(code)
        if holdings:
            info.top_holdings = holdings

        # 获取场内价格
        market_data = self.fetch_market_price(code)
        if market_data:
            info.market_price = market_data.get("price", 0)
            info.market_open = market_data.get("open", 0)
            info.market_high = market_data.get("high", 0)
            info.market_low = market_data.get("low", 0)
            info.market_prev_close = market_data.get("prev_close", 0)
            info.market_volume = market_data.get("volume", 0)
            info.market_amount = market_data.get("amount", 0)
            info.market_change = market_data.get("change", 0)
            info.market_update_time = market_data.get("update_time", "")

        # 设置默认费率
        info.purchase_fee = 1.5
        info.redeem_fee_short = 1.5
        info.redeem_fee_mid = 0.75
        info.redeem_fee_long = 0.25
        info.trade_commission = 0.025
        info.stamp_tax = 0.05

        return info

    def _parse_table_value(self, html: str, label: str) -> Optional[str]:
        """
        从HTML表格中提取指定标签对应的值
        支持 <th>标签</th><td>值</td> 和 <td>标签</td><td>值</td> 两种格式
        """
        # 模式1: <th>标签</th><td>值</td>
        pattern1 = rf'<th[^>]*>\s*{re.escape(label)}\s*</th>\s*<td[^>]*>(.*?)</td>'
        m = re.search(pattern1, html, re.DOTALL)
        if m:
            val = m.group(1).strip()
            # 去除HTML标签
            val = re.sub(r'<[^>]+>', '', val).strip()
            return val if val else None

        # 模式2: <td>标签</td><td>值</td>
        pattern2 = rf'<td[^>]*>\s*{re.escape(label)}\s*</td>\s*<td[^>]*>(.*?)</td>'
        m = re.search(pattern2, html, re.DOTALL)
        if m:
            val = m.group(1).strip()
            val = re.sub(r'<[^>]+>', '', val).strip()
            return val if val else None

        return None

    def _parse_fund_info_html(self, html: str, info: FundInfo) -> FundInfo:
        """解析天天基金基金档案页"""
        # 基金名称/简称
        name = self._parse_table_value(html, "基金简称")
        if not name:
            name = self._parse_table_value(html, "基金名称")
        if name:
            info.name = name

        # 基金代码
        code_val = self._parse_table_value(html, "基金代码")
        if code_val:
            m = re.search(r'(\d{6})', code_val)
            if m:
                info.code = m.group(1)

        # 基金类型
        ftype = self._parse_table_value(html, "基金类型")
        if ftype:
            info.fund_type = ftype

        # 基金经理
        manager = self._parse_table_value(html, "基金经理")
        if manager:
            info.manager = manager

        # 基金管理人
        company = self._parse_table_value(html, "基金管理人")
        if company:
            info.company = company

        # 资产规模
        size_text = self._parse_table_value(html, "净资产规模")
        if not size_text:
            size_text = self._parse_table_value(html, "资产规模")
        if size_text:
            m = re.search(r'([\d.]+)\s*亿元', size_text)
            if m:
                info.size = float(m.group(1))

        # 份额规模
        shares_text = self._parse_table_value(html, "份额规模")
        if shares_text:
            m = re.search(r'([\d.]+)\s*亿份', shares_text)
            if m:
                info.shares = float(m.group(1))

        # 管理费率
        fee_text = self._parse_table_value(html, "管理费率")
        if fee_text:
            m = re.search(r'([\d.]+)%', fee_text)
            if m:
                info.management_fee = float(m.group(1))

        # 托管费率
        fee_text = self._parse_table_value(html, "托管费率")
        if fee_text:
            m = re.search(r'([\d.]+)%', fee_text)
            if m:
                info.custodian_fee = float(m.group(1))

        # 业绩比较基准
        benchmark = self._parse_table_value(html, "业绩比较基准")
        if benchmark:
            info.benchmark = benchmark

        # 跟踪标的
        tracking = self._parse_table_value(html, "跟踪标的")
        if tracking:
            info.tracking_index = tracking

        # 风险等级
        risk = self._parse_table_value(html, "风险等级")
        if risk:
            info.risk_level = risk

        # 判断交易所
        if info.code.startswith(("50", "51", "58", "56")):
            info.exchange = "SH"
        elif info.code.startswith(("15", "16", "18")):
            info.exchange = "SZ"
        info.short_name = info.name[:8] if info.name else ""

        return info

    # ------------------- 净值数据 -------------------

    def fetch_latest_nav(self, code: str) -> Optional[Dict]:
        """获取最新净值"""
        # 尝试天天基金净值接口
        url = f"https://fundgz.1234567.com.cn/js/{code}.js?rt={int(time.time()*1000)}"
        text = self._get(url)
        if text and "jsonpgz" in text:
            # 解析JSONP格式: jsonpgz({...})
            m = re.search(r'jsonpgz\((.*)\)', text)
            if m:
                try:
                    data = json.loads(m.group(1))
                    return {
                        "nav": float(data.get("dwjz", 0)),
                        "date": data.get("jzrq", ""),
                        "change": float(data.get("gszzl", 0)),
                        "estimated_nav": float(data.get("gsz", 0)),
                        "estimate_time": data.get("gztime", ""),
                        "name": data.get("name", ""),
                    }
                except (json.JSONDecodeError, ValueError):
                    pass

        # 尝试天天基金历史净值页
        html = self._get(f"https://fundf10.eastmoney.com/jjjz_{code}.html")
        if html:
            return self._parse_latest_nav_html(html)

        return None

    def _parse_latest_nav_html(self, html: str) -> Optional[Dict]:
        """从净值页解析最新净值"""
        # 方式1: 从页面顶部的大数字显示中提取
        # 格式: 单位净值（07-23）： ... 1.7175 ( -2.91% )
        pattern1 = r'单位净值[^<]*<[^>]*>[\s\S]*?([\d.]+)\s*\(\s*([-\d.]+)%\s*\)'
        m = re.search(pattern1, html)
        if m:
            try:
                nav = float(m.group(1))
                change = float(m.group(2))
                # 尝试提取日期
                date_m = re.search(r'单位净值[（(]([^）)]+)[）)]', html)
                date_str = ""
                if date_m:
                    date_part = date_m.group(1).strip()
                    # 格式可能是 "07-23"，补充年份
                    if re.match(r'\d{2}-\d{2}', date_part):
                        from datetime import datetime
                        year = datetime.now().year
                        date_str = f"{year}-{date_part}"
                return {"nav": nav, "date": date_str, "change": change}
            except (ValueError, IndexError):
                pass

        # 方式2: 从历史净值表格中提取
        pattern = r'<tr[^>]*>\s*<td[^>]*>(\d{4}-\d{2}-\d{2})</td>\s*<td[^>]*>([\d.]+)</td>'
        matches = re.findall(pattern, html)
        if matches:
            date_str, nav_str = matches[0]
            try:
                nav = float(nav_str)
                # 尝试获取涨跌幅（第4列）
                change_pattern = r'<tr[^>]*>\s*<td[^>]*>' + re.escape(date_str) + r'</td>\s*<td[^>]*>[\d.]+</td>\s*<td[^>]*>[\d.]+</td>\s*<td[^>]*>([^<]+)</td>'
                change_m = re.search(change_pattern, html)
                change = 0.0
                if change_m:
                    change_text = change_m.group(1).strip()
                    m2 = re.search(r'([-\d.]+)%', change_text)
                    if m2:
                        change = float(m2.group(1))
                return {"nav": nav, "date": date_str, "change": change}
            except ValueError:
                pass
        return None

    def fetch_prev_nav(self, code: str) -> Optional[float]:
        """获取前一交易日净值"""
        html = self._get(f"https://fundf10.eastmoney.com/jjjz_{code}.html")
        if html:
            pattern = r'<tr[^>]*>\s*<td[^>]*>\d{4}-\d{2}-\d{2}</td>\s*<td[^>]*>([\d.]+)</td>'
            matches = re.findall(pattern, html)
            if len(matches) >= 2:
                try:
                    return float(matches[1])
                except ValueError:
                    pass
        return None

    def fetch_nav_history(self, code: str, days: int = 30) -> List[Tuple[str, float, float]]:
        """
        获取历史净值
        返回列表：[(日期, 单位净值, 涨跌幅), ...]
        """
        result = []
        html = self._get(f"https://fundf10.eastmoney.com/jjjz_{code}.html")
        if html:
            pattern = r'<tr[^>]*>\s*<td[^>]*>(\d{4}-\d{2}-\d{2})</td>\s*<td[^>]*>([\d.]+)</td>\s*<td[^>]*>[\d.]+</td>\s*<td[^>]*>([^<]+)</td>'
            matches = re.findall(pattern, html)
            for date_str, nav_str, change_str in matches[:days]:
                try:
                    nav = float(nav_str)
                    change = 0.0
                    m = re.search(r'([-\d.]+)%', change_str)
                    if m:
                        change = float(m.group(1))
                    result.append((date_str, nav, change))
                except ValueError:
                    continue
        return result

    # ------------------- 持仓数据 -------------------

    def fetch_holdings(self, code: str) -> List[Holding]:
        """获取基金前十大重仓股"""
        holdings = []

        # 方式1: 通过天天基金API接口获取（推荐，数据结构化）
        if self.session:
            try:
                api_url = (
                    f"https://fundf10.eastmoney.com/FundArchivesDatas.aspx"
                    f"?type=jjcc&code={code}&topline=10&year=&month=&rt={int(time.time()*1000)}"
                )
                resp = self.session.get(api_url, timeout=self.timeout,
                                        headers={"Referer": "https://fundf10.eastmoney.com/"})
                resp.encoding = resp.apparent_encoding or "utf-8"
                if resp.status_code == 200 and resp.text:
                    # 提取content字段中的HTML
                    m = re.search(r'content:"([\s\S]*?)",arryear', resp.text)
                    if m:
                        html_content = m.group(1)
                        holdings = self._parse_holdings_api_html(html_content)
            except Exception:
                pass

        # 方式2: 从持仓页面解析（备选）
        if not holdings:
            html = self._get(f"https://fundf10.eastmoney.com/ccmx_{code}.html")
            if html:
                holdings = self._parse_holdings_html(html)

        return holdings

    def _parse_holdings_api_html(self, html: str) -> List[Holding]:
        """解析持仓API返回的HTML内容"""
        holdings = []
        # 表格行格式：序号 | 股票代码 | 股票名称 | 最新价 | 涨跌幅 | 资讯 | 占净值比例 | 持股数 | 持仓市值
        # 注意：占净值比例列带%号，持仓市值可能带逗号
        pattern = (
            r'<tr[^>]*>\s*'
            r'<td[^>]*>\d+</td>\s*'
            r'<td[^>]*>(?:<a[^>]*>)?(\d{6})(?:</a>)?</td>\s*'
            r'<td[^>]*>(?:<a[^>]*>)?([^<]+)(?:</a>)?</td>\s*'
            r'<td[^>]*>.*?</td>\s*'
            r'<td[^>]*>.*?</td>\s*'
            r'<td[^>]*>.*?</td>\s*'
            r'<td[^>]*>([\d.,]+)%?</td>\s*'
            r'<td[^>]*>([\d.,]+)</td>\s*'
            r'<td[^>]*>([\d.,]+)</td>'
        )
        matches = re.findall(pattern, html)
        for stock_code, name, ratio_str, shares_str, value_str in matches[:10]:
            try:
                # 去掉逗号
                ratio = float(ratio_str.replace(',', ''))
                shares = float(shares_str.replace(',', ''))
                value = float(value_str.replace(',', ''))
                holding = Holding(
                    code=stock_code,
                    name=name.strip(),
                    ratio=ratio,
                    shares=shares,
                    market_value=value,
                )
                holdings.append(holding)
            except (ValueError, IndexError):
                continue

        return holdings

    def _parse_holdings_html(self, html: str) -> List[Holding]:
        """解析持仓页面（备用方法）"""
        holdings = []
        # 匹配持仓表格行
        pattern = (
            r'<tr[^>]*>\s*'
            r'<td[^>]*>\s*\d+\s*</td>\s*'
            r'<td[^>]*>(?:<a[^>]*>)?([^<]+)(?:</a>)?</td>\s*'
            r'<td[^>]*>(?:<a[^>]*>)?(\d{6})(?:</a>)?</td>\s*'
            r'<td[^>]*>([\d.]+)</td>\s*'
            r'<td[^>]*>([\d.]+)</td>\s*'
            r'<td[^>]*>([\d.]+)</td>'
        )
        matches = re.findall(pattern, html)
        for name, stock_code, ratio_str, shares_str, value_str in matches[:10]:
            try:
                holding = Holding(
                    code=stock_code,
                    name=name.strip(),
                    ratio=float(ratio_str),
                    shares=float(shares_str),
                    market_value=float(value_str),
                )
                holdings.append(holding)
            except ValueError:
                continue

        # 如果上面的正则没匹配到，尝试另一种格式
        if not holdings:
            pattern2 = (
                r'<tr[^>]*>\s*'
                r'<td[^>]*>(\d+)</td>\s*'
                r'<td[^>]*>([^<]+)</td>\s*'
                r'<td[^>]*>(\d{6})</td>\s*'
                r'<td[^>]*>([\d.]+)</td>'
            )
            matches2 = re.findall(pattern2, html)
            for _, name, stock_code, ratio_str in matches2[:10]:
                try:
                    holding = Holding(
                        code=stock_code,
                        name=name.strip(),
                        ratio=float(ratio_str),
                    )
                    holdings.append(holding)
                except ValueError:
                    continue

        return holdings

    # ------------------- 场内行情 -------------------

    def fetch_market_price(self, code: str) -> Optional[Dict]:
        """获取场内交易价格"""
        # 确定市场前缀
        if code.startswith(("50", "51", "58", "56", "60", "68")):
            market_prefix = "sh"
        else:
            market_prefix = "sz"

        # 尝试新浪财经行情接口
        sina_code = f"{market_prefix}{code}"
        url = f"https://hq.sinajs.cn/list={sina_code}"
        text = self._get(url, headers={"Referer": "https://finance.sina.com.cn"})
        if text:
            data = self._parse_sina_quote(text, sina_code)
            if data:
                return data

        # 尝试东方财富行情
        secid = f"1.{code}" if market_prefix == "sh" else f"0.{code}"
        url = f"https://push2.eastmoney.com/api/qt/stock/get?secid={secid}&fields=f43,f44,f45,f46,f47,f48,f60,f168,f169,f170"
        text = self._get(url)
        if text:
            try:
                data = json.loads(text)
                d = data.get("data", {})
                if d:
                    return {
                        "price": d.get("f43", 0) / 100 if d.get("f43") else 0,
                        "open": d.get("f46", 0) / 100 if d.get("f46") else 0,
                        "high": d.get("f44", 0) / 100 if d.get("f44") else 0,
                        "low": d.get("f45", 0) / 100 if d.get("f45") else 0,
                        "prev_close": d.get("f60", 0) / 100 if d.get("f60") else 0,
                        "volume": d.get("f47", 0) / 100 if d.get("f47") else 0,
                        "amount": d.get("f48", 0) / 10000 if d.get("f48") else 0,
                        "change": d.get("f170", 0) / 100 if d.get("f170") else 0,
                        "update_time": "",
                    }
            except (json.JSONDecodeError, KeyError, TypeError):
                pass

        return None

    def _parse_sina_quote(self, text: str, code: str) -> Optional[Dict]:
        """解析新浪行情数据"""
        # 格式: var hq_str_sh501098="科创建信LOF,1.764,1.800,1.708,...";
        pattern = rf'var hq_str_{code}="([^"]*)";'
        m = re.search(pattern, text)
        if m:
            fields = m.group(1).split(",")
            if len(fields) >= 10:
                try:
                    # 新浪行情字段：名称,今开,昨收,最新,最高,最低,...
                    return {
                        "name": fields[0],
                        "open": float(fields[1]),
                        "prev_close": float(fields[2]),
                        "price": float(fields[3]),
                        "high": float(fields[4]),
                        "low": float(fields[5]),
                        "volume": float(fields[8]) / 100 if fields[8] else 0,  # 手
                        "amount": float(fields[9]) / 10000 if fields[9] else 0,  # 万元
                        "change": ((float(fields[3]) - float(fields[2])) / float(fields[2]) * 100) if float(fields[2]) > 0 else 0,
                        "update_time": fields[30] + " " + fields[31] if len(fields) > 31 else "",
                    }
                except (ValueError, IndexError):
                    pass
        return None

    # ------------------- 股票实时行情 -------------------

    def fetch_stock_realtime(self, code: str) -> Optional[Dict]:
        """获取股票实时行情"""
        # 确定市场
        if code.startswith(("60", "68", "50", "51", "58")):
            market = "sh"
        else:
            market = "sz"

        sina_code = f"{market}{code}"
        url = f"https://hq.sinajs.cn/list={sina_code}"
        text = self._get(url, headers={"Referer": "https://finance.sina.com.cn"})
        if text:
            pattern = rf'var hq_str_{sina_code}="([^"]*)";'
            m = re.search(pattern, text)
            if m:
                fields = m.group(1).split(",")
                if len(fields) >= 10:
                    try:
                        price = float(fields[3])
                        prev_close = float(fields[2])
                        change_pct = ((price - prev_close) / prev_close * 100) if prev_close > 0 else 0
                        return {
                            "name": fields[0],
                            "price": price,
                            "change_pct": change_pct,
                            "open": float(fields[1]),
                            "high": float(fields[4]),
                            "low": float(fields[5]),
                            "volume": float(fields[8]),
                            "amount": float(fields[9]),
                        }
                    except (ValueError, IndexError):
                        pass
        return None

    def fetch_stocks_realtime(self, codes: List[str]) -> Dict[str, Dict]:
        """批量获取股票实时行情"""
        result = {}
        if not codes:
            return result

        # 分批获取，每批最多30只
        batch_size = 30
        for i in range(0, len(codes), batch_size):
            batch = codes[i:i + batch_size]
            sina_codes = []
            for code in batch:
                if code.startswith(("60", "68", "50", "51", "58")):
                    sina_codes.append(f"sh{code}")
                else:
                    sina_codes.append(f"sz{code}")

            url = f"https://hq.sinajs.cn/list={','.join(sina_codes)}"
            text = self._get(url, headers={"Referer": "https://finance.sina.com.cn"})
            if text:
                for sina_code in sina_codes:
                    code = sina_code[2:]
                    pattern = rf'var hq_str_{sina_code}="([^"]*)";'
                    m = re.search(pattern, text)
                    if m:
                        fields = m.group(1).split(",")
                        if len(fields) >= 10 and fields[3]:
                            try:
                                price = float(fields[3])
                                prev_close = float(fields[2])
                                change_pct = ((price - prev_close) / prev_close * 100) if prev_close > 0 else 0
                                result[code] = {
                                    "name": fields[0],
                                    "price": price,
                                    "change_pct": change_pct,
                                }
                            except (ValueError, IndexError):
                                pass

            # 随机延迟，避免被封
            if i + batch_size < len(codes):
                time.sleep(random.uniform(0.2, 0.5))

        return result

    # ------------------- 指数行情 -------------------

    def fetch_index_realtime(self, index_code: str) -> Optional[Dict]:
        """
        获取指数实时行情
        index_code: 如 "000905" (中证500), "000001" (上证指数), "399006" (创业板指)
        """
        # 指数代码映射
        index_map = {
            "000905": "sh000905",  # 中证500
            "000300": "sh000300",  # 沪深300
            "000001": "sh000001",  # 上证指数
            "399001": "sz399001",  # 深证成指
            "399006": "sz399006",  # 创业板指
            "000688": "sh000688",  # 科创50
        }
        sina_code = index_map.get(index_code, f"sh{index_code}")

        url = f"https://hq.sinajs.cn/list={sina_code}"
        text = self._get(url, headers={"Referer": "https://finance.sina.com.cn"})
        if text:
            pattern = rf'var hq_str_{sina_code}="([^"]*)";'
            m = re.search(pattern, text)
            if m:
                fields = m.group(1).split(",")
                if len(fields) >= 5:
                    try:
                        # 指数格式：名称,当前点数,涨跌点,涨跌幅,...
                        name = fields[0]
                        current = float(fields[1]) if fields[1] else 0
                        prev_close = float(fields[2]) if fields[2] else 0
                        change_pct = float(fields[3]) if len(fields) > 3 and fields[3] else 0
                        return {
                            "name": name,
                            "current": current,
                            "prev_close": prev_close,
                            "change_pct": change_pct,
                            "high": float(fields[4]) if len(fields) > 4 and fields[4] else 0,
                            "low": float(fields[5]) if len(fields) > 5 and fields[5] else 0,
                            "volume": float(fields[6]) if len(fields) > 6 and fields[6] else 0,
                            "amount": float(fields[7]) if len(fields) > 7 and fields[7] else 0,
                        }
                    except (ValueError, IndexError):
                        pass
        return None

    # ------------------- 港股行情 -------------------

    def fetch_hk_stock_realtime(self, hk_code: str) -> Optional[Dict]:
        """获取港股实时行情（5位数字代码，如01347）"""
        # 港股代码补零到5位
        code = hk_code.zfill(5)
        sina_code = f"rt_hk{code}"
        url = f"https://hq.sinajs.cn/list={sina_code}"
        text = self._get(url, headers={"Referer": "https://finance.sina.com.cn"})
        if text:
            pattern = rf'var hq_str_{sina_code}="([^"]*)";'
            m = re.search(pattern, text)
            if m:
                fields = m.group(1).split(",")
                if len(fields) >= 6:
                    try:
                        price = float(fields[6]) if len(fields) > 6 and fields[6] else 0
                        prev_close = float(fields[3]) if fields[3] else 0
                        change_pct = 0
                        if prev_close > 0 and price > 0:
                            change_pct = (price - prev_close) / prev_close * 100
                        return {
                            "name": fields[1] if len(fields) > 1 else "",
                            "price": price,
                            "prev_close": prev_close,
                            "change_pct": change_pct,
                        }
                    except (ValueError, IndexError):
                        pass
        return None
