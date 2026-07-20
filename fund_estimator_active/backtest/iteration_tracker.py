"""backtest/iteration_tracker.py — 多算法横向对比 + 自动选优

跑 6 种主动基金算法, 选 MAE 最低的为本期最佳。
"""
from __future__ import annotations
import sys
from pathlib import Path
from datetime import date as Date

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backtest.run_backtest import main as run_main


def main():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default="2026-04-25")
    ap.add_argument("--end", default="2026-07-15")
    args = ap.parse_args()
    # 直接调 run_backtest.main (它已经做了全部工作)
    sys.argv = ["run_backtest.py", "--start", args.start, "--end", args.end]
    run_main()


if __name__ == "__main__":
    main()
