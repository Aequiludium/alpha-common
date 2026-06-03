"""交易日历 I/O 与数据验证"""

from __future__ import annotations

import shutil
from pathlib import Path

import polars as pl
from polars.exceptions import PolarsError

from . import _constants


def copy_packaged_file() -> Path:
    """Copy the packaged parquet file to the user-local working path."""
    _constants.FILE_PATH.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(_constants.PACKAGE_XCALS, _constants.FILE_PATH)
    return _constants.FILE_PATH


def ensure_local_file() -> Path:
    """Ensure the user-local working copy exists, copying from package if needed."""
    if not _constants.FILE_PATH.exists():
        copy_packaged_file()
    return _constants.FILE_PATH


def validate_schema(df: pl.DataFrame) -> pl.DataFrame:
    """Validate the parquet schema and normalize column ordering."""
    missing_columns = [name for name in _constants.REQUIRED_SCHEMA if name not in df.columns]
    if missing_columns:
        raise ValueError(f"Missing required columns: {missing_columns}")

    wrong_types = {
        name: (df.schema[name], dtype)
        for name, dtype in _constants.REQUIRED_SCHEMA.items()
        if df.schema[name] != dtype
    }
    if wrong_types:
        details = ", ".join(
            f"{name}={actual} (expected {expected})"
            for name, (actual, expected) in wrong_types.items()
        )
        raise ValueError(f"Invalid column types: {details}")

    return df.select(list(_constants.REQUIRED_SCHEMA)).sort(_constants.DATE_COLUMN)


def read_calendar_table() -> pl.DataFrame:
    """Read and validate the local parquet calendar table.

    If the local file is unreadable, falls back to the packaged copy.
    If BOTH are unavailable, raises ``RuntimeError`` with a clear message.
    """
    try:
        path = ensure_local_file()
        try:
            df = pl.read_parquet(path)
        except PolarsError:
            copy_packaged_file()
            df = pl.read_parquet(path)
    except (FileNotFoundError, OSError, PolarsError):
        raise RuntimeError(
            f"Failed to read calendar data: "
            f"local file {_constants.FILE_PATH} is unreadable "
            f"and the packaged file {_constants.PACKAGE_XCALS} is also "
            f"unavailable or invalid."
        ) from None
    return validate_schema(df)


def download_calendar_table(target_path: Path | None = None) -> Path:
    """Download the latest parquet calendar to *target_path* (or default)."""
    import urllib.request

    dest = target_path or _constants.FILE_PATH
    dest.parent.mkdir(parents=True, exist_ok=True)
    urllib.request.urlretrieve(_constants.FILE_URL, str(dest))
    return dest
