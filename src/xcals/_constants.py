"""交易日历常量定义"""

from __future__ import annotations

import importlib.resources
from pathlib import Path

import polars as pl

DATE_COLUMN = "date"
TRADING_DAY_COLUMN = "IfTradingDay"
REQUIRED_SCHEMA: dict[str, pl.DataType] = {
    "date": pl.Date,
    "IfTradingDay": pl.Int64,
    "IfWeekEnd": pl.Int64,
    "IfMonthEnd": pl.Int64,
    "IfQuarterEnd": pl.Int64,
    "IfYearEnd": pl.Int64,
}

FILE_PATH = Path.home() / ".xcals"
FILE_URL = "https://raw.githubusercontent.com/link-yundi/xcals/refs/heads/main/.xcals"
PACKAGE_XCALS = Path(importlib.resources.files("xcals").joinpath(".xcals"))
