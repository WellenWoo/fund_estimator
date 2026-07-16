#!/bin/bash
cd /workspace
python3 code/fund_estimator/backtest/iteration_tracker.py \
  --start 2026-04-25 --end 2026-07-14 > /workspace/iter_final.log 2>&1
echo "EXIT=$?" >> /workspace/iter_final.log
