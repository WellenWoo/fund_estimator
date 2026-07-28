"""商品基金 → 底层商品 / 期货品种 映射表。

设计动机
--------
- ITERATIONS §2 指出 "对于 LOF 160223 跟踪创业板指，v_index_full_no_cash
  MAE 仅 0.11pp"，核心原因是「指数日线 = 组合价值的无偏估计」。
- 商品 / 商品期货 LOF 没有指数，但有"标的品种"（如 161226 跟踪
  上期所白银期货 AG 主连）。本模块负责显式声明"哪只 LOF 跟踪哪个
  品种"，是后续所有算法的基础。

字段说明
--------
- ``fund_code``   6 位 LOF / ETF 代码
- ``fund_name``   基金简称
- ``commodity``   底层商品中文名（白银 / 黄金 / 铜 / 原油 …）
- ``symbol``      新浪 hq.sinajs.cn 实时行情代码
                  （如 ``AG0`` = 上期所白银主连）
- ``exchange``    交易所简称（SHFE / SGE / DCE …）
- ``beta``        基金相对底层品种的 beta 系数（默认 1.0）
                  1.0 表示「基金日涨跌 ≈ 品种日涨跌」
- ``fee_drag_pp``  每日费率拖累（百分点），按 0.65%/年化折算约 0.0018/天
                  这里的默认 0.018pp/天 = 6.5bp/天（按 0.65% 年化）
                  算法可选择是否扣减
- ``contract``    合约描述（如 "AG 主连"、"Au99.99"）
- ``notes``       备注：跟踪方式 / 备注

扩展
----
新增商品基金时，仅需在本表追加一条记录即可。算法层通过
``get_commodity_for_fund(code)`` 自动查找。

参考 ITERATIONS §1「v_index_full_no_cash」bias 校准中观察到的
"指数本身漂移抵消费率"现象：商品 LOF 的费率拖累也会被期货
移仓损益部分抵消，因此本模块默认 ``fee_drag_pp`` 留 0，
让算法从实测中校准（与 ITERATIONS §2 同样的思路）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class CommodityInfo:
    """商品基金 → 底层品种的映射。"""

    fund_code: str
    fund_name: str
    commodity: str              # 底层商品中文名
    symbol: str                 # 新浪 hq 代码（如 AG0 / AU0 / SC0）
    exchange: str = "SHFE"      # 交易所
    contract: str = ""          # 合约描述
    beta: float = 1.0           # 基金相对品种的 beta（默认 1.0）
    fee_drag_pp: float = 0.0    # 每日费率拖累（百分点），默认 0
    notes: str = ""

    def to_dict(self) -> dict:
        return {
            "fund_code": self.fund_code,
            "fund_name": self.fund_name,
            "commodity": self.commodity,
            "symbol": self.symbol,
            "exchange": self.exchange,
            "contract": self.contract,
            "beta": self.beta,
            "fee_drag_pp": self.fee_drag_pp,
            "notes": self.notes,
        }


# --------------------------------------------------------------------------- #
# 商品基金映射表
# --------------------------------------------------------------------------- #
COMMODITY_MAP: dict[str, CommodityInfo] = {
    "161226": CommodityInfo(
        fund_code="161226",
        fund_name="国投瑞银白银期货(LOF)A",
        commodity="白银",
        symbol="nf_AG0",            # 新浪 hq：上期所白银主连（南华指数 nhtype）
        exchange="SHFE",
        contract="AG 主连 (上期所白银期货主力连续)",
        beta=1.0,
        fee_drag_pp=0.018,           # 0.65%/年化 → 0.0018/天（可校准）
        notes=(
            "持有上期所白银期货主力合约，现金部分投资于货币市场工具。"
            "2011 年成立，跟踪误差 ≤ 0.35%/年。SGZT=暂停申购 / SHZT=开放赎回 "
            "（按 lof_database/active_lofs 的最新记录）。"
            "新浪 hq 实际可用 symbol：nf_AG0（AG0 是 2024 年前老映射）。"
        ),
    ),
    # 预留常见商品基金的扩展位（实际生产前需手工核对）
    # 黄金 LOF 示例（518880 是 ETF 黄金，不是 LOF；此处仅占位）：
    # "518880": CommodityInfo(
    #     fund_code="518880",
    #     fund_name="华安黄金易ETF",
    #     commodity="黄金",
    #     symbol="AU0",
    #     exchange="SHFE",
    #     contract="AU 主连 (上期所黄金期货主力连续)",
    #     beta=1.0,
    #     notes="黄金 ETF（实际跟踪 SGE Au99.99 现货，AU0 仅作参考）",
    # ),
    # "161815": CommodityInfo(
    #     fund_code="161815",
    #     fund_name="银华抗通胀主题(LOF)",
    #     commodity="综合商品",
    #     symbol="",  # 综合商品无单一期货对应
    #     exchange="MULTI",
    #     contract="综合商品篮子（标普 GSCI / DJ-UBS 等）",
    #     notes="本模块暂不支持综合商品 LOF，需另写综合指数代理",
    # ),
}


def get_commodity_for_fund(fund_code: str) -> Optional[CommodityInfo]:
    """根据基金代码查底层商品映射，未收录返回 None。"""
    return COMMODITY_MAP.get(fund_code)


def list_supported_funds() -> list[CommodityInfo]:
    """返回本模块当前支持的所有商品基金列表。"""
    return list(COMMODITY_MAP.values())


__all__ = [
    "CommodityInfo",
    "COMMODITY_MAP",
    "get_commodity_for_fund",
    "list_supported_funds",
]
