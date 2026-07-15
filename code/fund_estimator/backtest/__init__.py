"""回测层。

- run_backtest.py         主回测入口（持仓还原为主）
- run_index_backtest.py   创业板指代理回测
- iteration_tracker.py    多方法横向对比 + 选优
"""

from .run_backtest import backtest_range, load_common_inputs
from .run_index_backtest import backtest_index_range

__all__ = ["backtest_range", "load_common_inputs", "backtest_index_range"]
