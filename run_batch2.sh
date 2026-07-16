#!/bin/bash
cd /workspace
python3 -u code/fund_estimator/scripts/batch_daily_run.py \
  --start 2026-04-25 --end 2026-07-06 \
  --method v_index_full_no_cash \
  > /workspace/batch_no_cash.log 2>&1
echo "EXIT=$?" >> /workspace/batch_no_cash.log
