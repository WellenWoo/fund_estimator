"""估值算法：持仓还原法（v1）。

逻辑：
    estimated_nav ≈ (Σ_i  pct_i * (1 + r_i)) + (1 - Σ_i pct_i) * factor_cash
其中 pct_i 是股票 i 占基金净值的权重，r_i 是股票 i 的当日涨跌幅。
factor_cash 表示现金部分的近似收益（货币基金利率 / 0%）。

权重来源：东方财富 pingzhongdata 的 stockCodes + Data_fundSharesPositions
        我们取 top_n 个披露持仓 × 最新股票仓位（约 95%），剩余按 cash 部分处理。
        注意：v1 暂未取得"每个持仓股的具体占净值比"，所以做了一个保守估计：
            假设 top10 等权重，每只占 (stock_pct * 1.2) / top_n；
            系数 1.2 是行业经验值（top10 持仓在指数型基金约占 30%，但创业板集中度高）。
        这是 v1 的最大误差源，v2 会把"持仓权重"补齐。
"""

from __future__ import annotations

from dataclasses import dataclass

from ..core.models import (
    FundHolding,
    NAVEstimate,
    RealtimeQuote,
    StockPosition,
)


@dataclass
class WeightPolicy:
    """v1：top10 等权重 + 现金部分近似。"""

    top_n: int = 10
    # 假设 top10 持仓股票累计占净值的比重（剩余为现金/低仓位股）。
    # 跟踪纯被动指数基金时，top10 累计权重通常 > 30%。
    disclosed_collective_pct: float = 40.0

    def assign_weights(self, holding: FundHolding) -> dict[str, float]:
        positions = holding.stock_positions[: self.top_n]
        n = len(positions) if positions else 1
        # 每只等权分摊 disclosed_collective_pct%
        per = self.disclosed_collective_pct / n
        return {p.code: per for p in positions}


def estimate_change_pct(
    holding: FundHolding,
    quotes: list[RealtimeQuote],
    policy: WeightPolicy | None = None,
) -> tuple[float, dict]:
    """根据持仓 + 实时行情，计算基金的估算涨跌幅。

    returns: (estimated_change_pct, components)
        components: {"300750": {"weight": 5.0, "change_pct": 1.2, "contrib": 0.06}}
    """
    if policy is None:
        policy = WeightPolicy()
    weights = policy.assign_weights(holding)

    quote_map = {f"{q.market}{q.code}": q for q in quotes}

    components: dict[str, dict] = {}
    weighted_change = 0.0
    total_weight = 0.0

    for code, weight in weights.items():
        # 优先按 SZ 找，找不到试 SH（A 股主 99% 落在 SZ/SH 二选一）
        q = quote_map.get(f"SZ{code}") or quote_map.get(f"SH{code}")
        if q is None or q.prev_close <= 0:
            continue
        contrib = (q.change_pct / 100.0) * weight
        weighted_change += contrib
        total_weight += weight
        components[code] = {
            "weight": round(weight, 4),
            "change_pct": round(q.change_pct, 4),
            "contrib": round(contrib, 6),
        }

    # 缺失的持仓股：保守按 0% 处理（不放大也不抵销）
    return weighted_change, components


def estimate_nav(
    holding: FundHolding,
    quotes: list[RealtimeQuote],
    last_official_nav: float,
    policy: WeightPolicy | None = None,
) -> NAVEstimate:
    """整合：把估算涨跌幅应用在最近一次官方净值上，得到估算净值。"""
    from datetime import datetime

    pct, components = estimate_change_pct(holding, quotes, policy)
    estimated = last_official_nav * (1 + pct / 100.0)
    return NAVEstimate(
        fund_code=holding.fund_code,
        estimate_time=datetime.now(),
        estimated_nav=round(estimated, 4),
        estimated_change_pct=round(pct, 4),
        method="holdings_based_v1",
        components=components,
    )
