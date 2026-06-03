"""交易日历存储模块（内部实现）"""

from __future__ import annotations

import bisect
import shutil
import tempfile
import uuid
from pathlib import Path

import polars as pl

from . import _constants, _io


class Calendar:
    """A singleton class for managing trading calendar data."""

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        """Construct the singleton.  No I/O — data loads lazily on first use."""
        if getattr(self, "_ready", False):
            return
        self._ready = False

    # -- internal helpers ----------------------------------------------------

    def _ensure_loaded(self) -> None:
        """Lazy-load calendar data on first access."""
        if self._ready:
            return
        self.reload()

    def _rebuild_indexes(self) -> None:
        """Rebuild the trading-day list and set from ``self._table``."""
        trading_days = (
            self._table.filter(pl.col(_constants.TRADING_DAY_COLUMN) == 1)
            .select(
                pl.col(_constants.DATE_COLUMN).dt.strftime("%Y-%m-%d").alias(_constants.DATE_COLUMN)
            )
            .get_column(_constants.DATE_COLUMN)
            .to_list()
        )
        # Assign list first, then set — both are built from the SAME local
        # ``trading_days`` so the inconsistency window is bounded to the
        # set-construction call below.
        self._trading_days = trading_days
        self._trading_day_set = set(trading_days)

    def reload(self) -> None:
        """Force-reload the parquet table and rebuild cached indexes."""
        self._table = _io.read_calendar_table()
        self._rebuild_indexes()
        self._ready = True

    def update(self) -> None:
        """Download the latest calendar, validate it, atomically replace."""
        tmp = Path(tempfile.mktemp())
        try:
            print(f"Downloading calendar from {_constants.FILE_URL} to {_constants.FILE_PATH}...")
            _io.download_calendar_table(tmp)

            # Validate BEFORE replacing the live file.
            _io.validate_schema(pl.read_parquet(tmp))
            print("Download completed.")

            _constants.FILE_PATH.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(tmp), str(_constants.FILE_PATH))
            self.reload()
        except Exception:
            print("Failed to update calendar.")
            if tmp.exists():
                tmp.unlink()
            raise

    # -- public query API ----------------------------------------------------

    def get_tradingdays(
        self,
        beg_date: str | None = None,
        end_date: str | None = None,
    ) -> pl.DataFrame:
        """Get trading days within a range."""
        self._ensure_loaded()
        result = self._table.filter(pl.col(_constants.TRADING_DAY_COLUMN) == 1)
        if beg_date is not None:
            result = result.filter(pl.col(_constants.DATE_COLUMN) >= pl.lit(beg_date).str.to_date())
        if end_date is not None:
            result = result.filter(pl.col(_constants.DATE_COLUMN) <= pl.lit(end_date).str.to_date())
        return result.select(_constants.DATE_COLUMN)

    def get_tradingdays_lag(self, date: str, num: int) -> pl.DataFrame:
        """Get the last ``num`` trading days up to ``date``."""
        self._ensure_loaded()
        result = self._table.filter(
            (pl.col(_constants.TRADING_DAY_COLUMN) == 1)
            & (pl.col(_constants.DATE_COLUMN) <= pl.lit(date).str.to_date())
        )
        return result.select(_constants.DATE_COLUMN).tail(abs(num))

    def get_recent_tradeday(self, date: str) -> str:
        """Get the most recent trading day on or before ``date``."""
        self._ensure_loaded()
        idx = bisect.bisect_right(self._trading_days, date)
        if idx == 0:
            raise ValueError(f"No trading day found before or on {date}")
        return self._trading_days[idx - 1]

    def shift_tradeday(self, date: str, num: int = 1) -> str:
        """Shift a date by ``num`` trading days."""
        self._ensure_loaded()
        if num == 0:
            return date

        if num > 0:
            idx = bisect.bisect_left(self._trading_days, date)
            target_idx = idx + num
        else:
            idx = bisect.bisect_right(self._trading_days, date)
            target_idx = idx + num - 1

        if 0 <= target_idx < len(self._trading_days):
            return self._trading_days[target_idx]
        raise IndexError(f"Shifted date out of range: {date} + {num}")

    def is_tradeday(self, date: str) -> bool:
        """Check whether ``date`` is a trading day."""
        self._ensure_loaded()
        return date in self._trading_day_set

    def is_reportdate(self, date: str) -> bool:
        """Check whether ``date`` is a standard quarterly report date."""
        try:
            _, month, day = map(int, date.split("-"))
        except ValueError:
            return False

        if month in [6, 9]:
            return day == 30
        if month in [3, 12]:
            return day == 31
        return False

    def align_trade_date(
        self,
        df: pl.DataFrame,
        date_col: str = _constants.DATE_COLUMN,
        method: str = "backward",
        trade_date_col: str = "trade_date",
    ) -> pl.DataFrame:
        """Align natural dates to nearest trading dates via asof join."""
        self._ensure_loaded()
        trade_dates = (
            self._table.filter(pl.col(_constants.TRADING_DAY_COLUMN) == 1)
            .select(pl.col(_constants.DATE_COLUMN).alias(trade_date_col))
            .sort(trade_date_col)
        )

        row_idx_col = f"_xcals_row_idx_{uuid.uuid4().hex}"

        return (
            df.with_row_index(row_idx_col)
            .sort(date_col)
            .join_asof(
                trade_dates,
                left_on=date_col,
                right_on=trade_date_col,
                strategy=method,
            )
            .sort(row_idx_col)
            .drop(row_idx_col)
        )
