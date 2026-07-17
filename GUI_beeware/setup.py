#!/usr/bin/env python
"""setup.py for LOF Fund Valuation GUI (Toga/Beeware)"""
from setuptools import setup, find_packages

setup(
    name="lof-fund-valuator",
    version="0.1.0",
    description="LOF Fund Real-time Valuation GUI (Toga/Beeware)",
    packages=find_packages(),
    python_requires=">=3.10",
    install_requires=[
        "toga>=0.5.0",
    ],
    entry_points={
        "toga.applications": [
            "__main__" = "lof_valuator",
        ],
    },
)
