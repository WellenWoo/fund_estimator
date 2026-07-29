"""债券型基金 → 底层代理指数 / 持仓类型 映射表。

设计动机
========
ITERATIONS §3 验证了「对 LOF 160223 用指数日线直接代理 NAV → MAE 0.11pp」，
本质是「指数 = 组合」——组合复制了指数。

债基不能这样：
- 纯债基（如 164703 汇添富纯债(LOF)A）底层是「利率债 + 信用债 + 少量股票」，
  **没有公开可复制的指数**。
- 季报披露的「前 5 大持仓」是**债券代码**（如 24 国债 09 / 23 附息国债 04），
  占比 30-50%；剩余 50-70% 是分散的小持仓，**没有公开的债券 ETF / 指数能完整覆盖**。
- 净值日波动极小（实测 ±0.05pp），用股票指数（如中证 1000）作长尾代理完全不相关（量级差 100 倍）。

正确做法
========
用**公开可观测的债券指数**作为代理：
- 沪深企业债指数 (sh000061) — 全市场企业债，**波动与纯债基日收益同量级**（实测日波动 0.05%）
- 上证国债指数 (sh000012) — 利率债，**久期/利率敏感度更高**（日波动 0.006%）
- 上证公司债指数 (sh000022) — 信用债，介于两者之间（日波动 0.008%）

这些指数均可在新浪 ``hq.sinajs.cn`` 取到日线 K 线。

字段说明
========
- ``fund_code``     6 位 LOF 基金代码
- ``fund_name``     基金简称
- ``fund_subtype``  债券型细分（纯债 / 一级债基 / 二级债基 / 可转债债基 / 短债 / 中长债）
- ``primary_index`` 主代理指数（symbol, 名称）
- ``secondary_index`` 辅助参考指数（symbol, 名称）
- ``beta``          基金日收益对主代理指数日收益的回归斜率（默认 1.0 = 同等敏感度）
- ``fee_drag_pp``   每日费率拖累（百分点，默认 0；理由同 ITERATIONS §2 — 实际 0 比扣除更准）
- ``stock_position`` 股票底仓占比（%），混合债基 < 5%，二级债基 < 20%
- ``notes``         备注

扩展方式
========
新增债基时，仅需在本表追加一行。所有算法通过 ``get_bond_info_for_fund(code)`` 自动获取。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


@dataclass
class BondInfo:
    """债券型基金 → 底层代理的映射记录。"""

    fund_code: str
    fund_name: str
    fund_subtype: str = "纯债"          # 纯债 / 一级债基 / 二级债基 / 可转债债基 / 短债
    primary_index: tuple = ("sh000061", "沪深企业债指数")
    secondary_index: tuple = ("sh000012", "上证国债指数")
    beta: float = 1.0                  # 基金日收益对主代理的回归斜率
    fee_drag_pp: float = 0.0           # 每日费率拖累（pp）
    stock_position: float = 0.0        # 股票底仓占比（%）
    notes: str = ""

    def to_dict(self) -> dict:
        return {
            "fund_code": self.fund_code,
            "fund_name": self.fund_name,
            "fund_subtype": self.fund_subtype,
            "primary_index": {
                "symbol": self.primary_index[0],
                "name": self.primary_index[1],
            },
            "secondary_index": {
                "symbol": self.secondary_index[0],
                "name": self.secondary_index[1],
            },
            "beta": self.beta,
            "fee_drag_pp": self.fee_drag_pp,
            "stock_position": self.stock_position,
            "notes": self.notes,
        }


# ---------------------------------------------------------------------------
# 债基 → 代理指数 映射表
# ---------------------------------------------------------------------------
BOND_MAP: dict[str, BondInfo] = {
    "164703": BondInfo(
        fund_code="164703",
        fund_name="汇添富纯债(LOF)A",
        fund_subtype="纯债",
        primary_index=("sh000061", "沪深企业债指数"),
        secondary_index=("sh000012", "上证国债指数"),
        beta=1.0,
        fee_drag_pp=0.0,
        stock_position=0.0,
        notes=("季报披露持仓以政策性金融债 + 信用债为主，无股票底仓。"
               "债性最纯，沪深企业债指数是最佳代理。"),
    ),
    # 占位示例，便于扩展：
    # "160128": BondInfo(
    #     fund_code="160128",
    #     fund_name="南方金利定开债",
    #     fund_subtype="纯债",
    #     primary_index=("sh000022", "上证公司债指数"),
    #     ...
    # ),
}


def get_bond_info_for_fund(fund_code: str) -> Optional[BondInfo]:
    """根据基金代码获取 BondInfo，未注册则返回 None。"""
    return BOND_MAP.get(fund_code)


def list_supported_funds() -> list[str]:
    """返回已注册的债基代码列表。"""
    return list(BOND_MAP.keys())
