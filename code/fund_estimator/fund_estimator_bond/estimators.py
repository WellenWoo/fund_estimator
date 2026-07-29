"""债券型基金估值算法实现（5 种）。

与 ``fund_estimator.estimators.holdings_based`` / ``fund_estimator_product.estimators`` 的对比：

- 持仓还原 / 指数代理：债基的「前 5 大持仓」是**债券代码**（如 24 国债 09），
  公开市场虽能取 K 线，但单只券流动性差、做市价偏离大，因此纯持仓还原会引入
  不必要的噪声，本模块**默认不采用**；
- **本模块的核心思路 = 「公开债券指数作代理」**：
  - 沪深企业债指数 (sh000061) 全市场企业债，**日波动 0.05%，与纯债基日收益同量级**；
  - 上证国债指数 (sh000012) 利率债，**日波动 0.006%**，适合久期敏感型债基；
  - T-1 官方 NAV 涨跌% = 「底层债市当日收益」的无偏代理（参考 ITERATIONS §3 同思路）。

5 种算法
--------

+---------------+----------------------------------------------------+
| v_bond_csi_corp | T 涨跌% = 沪深企业债指数 (sh000061) 日涨跌%         |
|               | 主推 — 与纯债基日波动同量级，beta ≈ 1              |
+---------------+----------------------------------------------------+
| v_bond_sse_gov | T 涨跌% = 上证国债指数 (sh000012) 日涨跌%           |
|               | 备选 — 利率债型，波动更小，需配合更长持仓            |
+---------------+----------------------------------------------------+
| v_bond_t1_persist | T 涨跌% = T-1 涨跌%（动量 / 持久性代理）          |
|               | 仿 commodity.v_proxy                                |
+---------------+----------------------------------------------------+
| v_bond_random_walk | T 涨跌% = 0（无偏随机游走基线）                  |
|               | 仿 commodity.v_random_walk — 债基日波动 < 0.1pp，    |
|               | 「无新增信息」假设的基线                             |
+---------------+----------------------------------------------------+
| v_bond_blend  | 0.3 × T-1 + 0.7 × 0（保守动量混合）                 |
|               | 仿 commodity.v_blend                                |
+---------------+----------------------------------------------------+

注：所有算法对单日 NAV 的核心更新公式都遵循 README §4::

    估算 NAV(T) = T-1 NAV × (1 + 估算涨跌% / 100)

并支持 optional 的 ``fee_drag_pp``（每日费率拖累 pp），
用于模拟「按 0.65%/年化折算 0.018 pp/天」对结果的影响。
实际回测中 0 比扣除更准（与 ITERATIONS §2 同结论）。
"""

from __future__ import annotations

from typing import Optional

from ..core.models import NAVEstimate


# ---------------------------------------------------------------------------
# 算法注册表
# ---------------------------------------------------------------------------
DEFAULT_METHOD = "v_bond_csi_corp"
"""默认算法：沪深企业债指数直接代理。与纯债基日收益同量级，回归验证 beta ≈ 1。"""

METHODS = [
    "v_bond_csi_corp",
    "v_bond_sse_gov",
    "v_bond_t1_persist",
    "v_bond_random_walk",
    "v_bond_blend",
]

METHOD_LABELS = {
    "v_bond_csi_corp":     "沪深企业债指数 (sh000061) 直接代理 ⭐",
    "v_bond_sse_gov":      "上证国债指数 (sh000012) 直接代理",
    "v_bond_t1_persist":   "T-1 涨跌% 动量代理",
    "v_bond_random_walk":  "无偏随机游走 (T 涨跌% = 0) 基线",
    "v_bond_blend":        "0.3 × T-1 + 0.7 × 0 保守动量混合",
}


# ---------------------------------------------------------------------------
# 核心估算函数
# ---------------------------------------------------------------------------
def estimate(
    method: str,
    *,
    fund_code: str,
    today: str,
    t1_date: str,
    t1_nav: float,
    t1_change_pct: float = 0.0,
    bond_index_change_pct: float = 0.0,
    beta: float = 1.0,
    fee_drag_pp: float = 0.0,
    detail: Optional[dict] = None,
) -> NAVEstimate:
    """统一的债基估值入口。

    Parameters
    ----------
    method : str
        算法标识，须在 ``METHODS`` 中。
    fund_code : str
        6 位基金代码。
    today : str
        估值目标日期 T（YYYY-MM-DD）。
    t1_date : str
        基线日期 T-1（YYYY-MM-DD）。
    t1_nav : float
        T-1 官方单位净值。
    t1_change_pct : float, default 0.0
        T-1 官方涨跌%（= T-1 NAV 相对 T-2 NAV 的涨跌）。
        用于 ``v_bond_t1_persist`` / ``v_bond_blend``。
    bond_index_change_pct : float, default 0.0
        主代理债券指数的日涨跌%（如 sh000061 当日 %）。
        用于 ``v_bond_csi_corp`` / ``v_bond_sse_gov``。
    beta : float, default 1.0
        基金日收益对代理指数日收益的回归斜率。
    fee_drag_pp : float, default 0.0
        每日费率拖累（百分点），默认 0（与 ITERATIONS §2 同结论）。
    detail : dict, optional
        附加上下文（用于调试 / 报告）。

    Returns
    -------
    NAVEstimate
    """
    if method not in METHODS:
        raise ValueError(
            f"Unknown bond method: {method!r}. choices={METHODS}"
        )

    if method == "v_bond_csi_corp":
        est_pct = bond_index_change_pct * beta - fee_drag_pp
        used = "沪深企业债指数(sh000061)涨跌%"
    elif method == "v_bond_sse_gov":
        est_pct = bond_index_change_pct * beta - fee_drag_pp
        used = "上证国债指数(sh000012)涨跌%"
    elif method == "v_bond_t1_persist":
        est_pct = t1_change_pct - fee_drag_pp
        used = "T-1涨跌%(动量)"
    elif method == "v_bond_random_walk":
        est_pct = 0.0 - fee_drag_pp
        used = "0(无偏随机游走)"
    elif method == "v_bond_blend":
        est_pct = 0.3 * t1_change_pct - fee_drag_pp
        used = "0.3×T-1+0.7×0"
    else:
        # 不可能走到这里（METHODS 已校验）
        est_pct = 0.0
        used = "?"

    estimated_nav = t1_nav * (1.0 + est_pct / 100.0)

    d = {
        "method": method,
        "used_signal": used,
        "est_pct": round(est_pct, 6),
        "t1_change_pct": round(t1_change_pct, 4),
        "bond_index_change_pct": round(bond_index_change_pct, 4),
        "beta": beta,
        "fee_drag_pp": fee_drag_pp,
    }
    if detail:
        d.update(detail)

    return NAVEstimate(
        fund_code=fund_code,
        today=today,
        t1_date=t1_date,
        t1_nav=t1_nav,
        estimated_nav=round(estimated_nav, 4),
        estimated_change_pct=round(est_pct, 4),
        method=method,
        detail=d,
    )
