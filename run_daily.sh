#!/bin/bash
cd /workspace
python3 code/fund_estimator/scripts/daily_close_estimate.py \
  --trade-date 2026-07-06 --method v_index_full --fetch-official \
  > /workspace/daily_estimate.log 2>&1
echo "EXIT=$?" >> /workspace/daily_estimate.log
