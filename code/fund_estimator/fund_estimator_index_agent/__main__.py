"""Allow running as: python -m fund_estimator_index_agent"""

import os
import sys

# Ensure the fund_estimator package root is on sys.path
_THIS = os.path.dirname(os.path.abspath(__file__))
_CODE_ROOT = os.path.dirname(os.path.dirname(_THIS))  # code/
if _CODE_ROOT not in sys.path:
    sys.path.insert(0, _CODE_ROOT)

from fund_estimator.fund_estimator_index_agent import main

if __name__ == "__main__":
    raise SystemExit(main())
