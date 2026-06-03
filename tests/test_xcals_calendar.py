import datetime
from pathlib import Path

import polars as pl
import pytest

import xcals
from xcals import _constants, _io, _store


def _write_calendar(path: Path, rows: list[dict[str, object]]) -> None:
    pl.DataFrame(rows).write_parquet(path)


def _reset_calendar_singleton() -> None:
    _store.Calendar._instance = None


def _sample_calendar_rows() -> list[dict[str, object]]:
    return [
        {
            "date": datetime.date(2024, 1, 1),
            "IfTradingDay": 0,
            "IfWeekEnd": 0,
            "IfMonthEnd": 0,
            "IfQuarterEnd": 0,
            "IfYearEnd": 0,
        },
        {
            "date": datetime.date(2024, 1, 2),
            "IfTradingDay": 1,
            "IfWeekEnd": 0,
            "IfMonthEnd": 0,
            "IfQuarterEnd": 0,
            "IfYearEnd": 0,
        },
        {
            "date": datetime.date(2024, 1, 3),
            "IfTradingDay": 1,
            "IfWeekEnd": 0,
            "IfMonthEnd": 0,
            "IfQuarterEnd": 0,
            "IfYearEnd": 0,
        },
        {
            "date": datetime.date(2024, 1, 4),
            "IfTradingDay": 0,
            "IfWeekEnd": 0,
            "IfMonthEnd": 0,
            "IfQuarterEnd": 0,
            "IfYearEnd": 0,
        },
        {
            "date": datetime.date(2024, 1, 5),
            "IfTradingDay": 1,
            "IfWeekEnd": 0,
            "IfMonthEnd": 0,
            "IfQuarterEnd": 0,
            "IfYearEnd": 0,
        },
        {
            "date": datetime.date(2024, 1, 8),
            "IfTradingDay": 1,
            "IfWeekEnd": 0,
            "IfMonthEnd": 0,
            "IfQuarterEnd": 0,
            "IfYearEnd": 0,
        },
    ]


@pytest.fixture(autouse=True)
def reset_calendar_singleton():
    _reset_calendar_singleton()
    yield
    _reset_calendar_singleton()


def test_calendar_initializes_from_packaged_data(tmp_path, monkeypatch):
    package_file = tmp_path / ".xcals"
    local_file = tmp_path / "home" / ".xcals"
    _write_calendar(
        package_file,
        [
            {
                "date": datetime.date(2024, 1, 1),
                "IfTradingDay": 0,
                "IfWeekEnd": 0,
                "IfMonthEnd": 0,
                "IfQuarterEnd": 0,
                "IfYearEnd": 0,
            },
            {
                "date": datetime.date(2024, 1, 2),
                "IfTradingDay": 1,
                "IfWeekEnd": 0,
                "IfMonthEnd": 0,
                "IfQuarterEnd": 0,
                "IfYearEnd": 0,
            },
            {
                "date": datetime.date(2024, 1, 3),
                "IfTradingDay": 1,
                "IfWeekEnd": 0,
                "IfMonthEnd": 0,
                "IfQuarterEnd": 0,
                "IfYearEnd": 0,
            },
        ],
    )

    monkeypatch.setattr(_constants, "PACKAGE_XCALS", package_file)
    monkeypatch.setattr(_constants, "FILE_PATH", local_file)

    calendar = _store.Calendar()
    # Lazy load triggers copy from package → local
    assert calendar.is_tradeday("2024-01-02") is True
    assert local_file.exists()
    assert calendar.is_tradeday("2024-01-01") is False
    assert calendar.get_tradingdays("2024-01-01", "2024-01-03")["date"].to_list() == [
        datetime.date(2024, 1, 2),
        datetime.date(2024, 1, 3),
    ]


def test_calendar_rejects_invalid_parquet_schema(tmp_path, monkeypatch):
    package_file = tmp_path / ".xcals"
    local_file = tmp_path / "home" / ".xcals"
    pl.DataFrame(
        {
            "date": [datetime.date(2024, 1, 1)],
            "IfTradingDay": [0],
        }
    ).write_parquet(package_file)

    monkeypatch.setattr(_constants, "PACKAGE_XCALS", package_file)
    monkeypatch.setattr(_constants, "FILE_PATH", local_file)

    cal = _store.Calendar()
    with pytest.raises(ValueError, match="Missing required columns"):
        cal.is_tradeday("2024-01-01")  # triggers _ensure_loaded → validate_schema


def test_calendar_replaces_legacy_text_local_file(tmp_path, monkeypatch):
    package_file = tmp_path / ".xcals"
    local_file = tmp_path / "home" / ".xcals"
    _write_calendar(
        package_file,
        [
            {
                "date": datetime.date(2024, 1, 1),
                "IfTradingDay": 0,
                "IfWeekEnd": 0,
                "IfMonthEnd": 0,
                "IfQuarterEnd": 0,
                "IfYearEnd": 0,
            },
            {
                "date": datetime.date(2024, 1, 2),
                "IfTradingDay": 1,
                "IfWeekEnd": 0,
                "IfMonthEnd": 0,
                "IfQuarterEnd": 0,
                "IfYearEnd": 0,
            },
        ],
    )
    local_file.parent.mkdir(parents=True, exist_ok=True)
    local_file.write_text("2024-01-02\n", encoding="utf-8")

    monkeypatch.setattr(_constants, "PACKAGE_XCALS", package_file)
    monkeypatch.setattr(_constants, "FILE_PATH", local_file)

    calendar = _store.Calendar()

    assert calendar.is_tradeday("2024-01-02") is True
    assert pl.read_parquet(local_file).schema == pl.read_parquet(package_file).schema


def test_tradingday_api_preserves_existing_semantics(tmp_path, monkeypatch):
    package_file = tmp_path / ".xcals"
    local_file = tmp_path / "home" / ".xcals"
    _write_calendar(package_file, _sample_calendar_rows())

    monkeypatch.setattr(_constants, "PACKAGE_XCALS", package_file)
    monkeypatch.setattr(_constants, "FILE_PATH", local_file)

    calendar = _store.Calendar()
    monkeypatch.setattr(xcals.calendar, "CALENDAR", calendar)

    assert xcals.get_tradingdays("2024-01-01", "2024-01-05") == [
        "2024-01-02",
        "2024-01-03",
        "2024-01-05",
    ]
    assert xcals.get_tradingdays("2024-01-01", "2024-01-05", to_str=False) == [
        datetime.date(2024, 1, 2),
        datetime.date(2024, 1, 3),
        datetime.date(2024, 1, 5),
    ]
    assert xcals.get_last_tradingday("2024-01-04") == "2024-01-03"
    assert xcals.shift_tradeday("2024-01-04", 1) == "2024-01-08"
    assert xcals.shift_tradeday("2024-01-04", -1) == "2024-01-02"
    assert xcals.shift_tradeday("2024-01-04", 0) == "2024-01-04"


def test_align_trade_date_supports_backward_and_forward_fill(tmp_path, monkeypatch):
    package_file = tmp_path / ".xcals"
    local_file = tmp_path / "home" / ".xcals"
    _write_calendar(package_file, _sample_calendar_rows())

    monkeypatch.setattr(_constants, "PACKAGE_XCALS", package_file)
    monkeypatch.setattr(_constants, "FILE_PATH", local_file)

    calendar = _store.Calendar()
    monkeypatch.setattr(xcals.calendar, "CALENDAR", calendar)

    df = pl.DataFrame(
        {
            "date": [
                datetime.date(2023, 12, 31),
                datetime.date(2024, 1, 2),
                datetime.date(2024, 1, 4),
                datetime.date(2024, 1, 6),
                datetime.date(2024, 1, 9),
            ],
            "value": [1, 2, 3, 4, 5],
        }
    )

    backward = xcals.align_trade_date(df, method="backward")
    forward = xcals.align_trade_date(df, method="forward")

    assert backward["trade_date"].to_list() == [
        None,
        datetime.date(2024, 1, 2),
        datetime.date(2024, 1, 3),
        datetime.date(2024, 1, 5),
        datetime.date(2024, 1, 8),
    ]
    assert forward["trade_date"].to_list() == [
        datetime.date(2024, 1, 2),
        datetime.date(2024, 1, 2),
        datetime.date(2024, 1, 5),
        datetime.date(2024, 1, 8),
        None,
    ]
    assert backward["value"].to_list() == [1, 2, 3, 4, 5]


def test_align_trade_date_requires_date_column_and_preserves_custom_name(tmp_path, monkeypatch):
    package_file = tmp_path / ".xcals"
    local_file = tmp_path / "home" / ".xcals"
    _write_calendar(package_file, _sample_calendar_rows())

    monkeypatch.setattr(_constants, "PACKAGE_XCALS", package_file)
    monkeypatch.setattr(_constants, "FILE_PATH", local_file)

    calendar = _store.Calendar()
    monkeypatch.setattr(xcals.calendar, "CALENDAR", calendar)

    df = pl.DataFrame(
        {
            "natural_date": [datetime.date(2024, 1, 4)],
        }
    )
    result = xcals.align_trade_date(
        df,
        date_col="natural_date",
        trade_date_col="aligned_trade_date",
    )
    assert result["aligned_trade_date"].to_list() == [datetime.date(2024, 1, 3)]

    bad_df = pl.DataFrame({"date": ["2024-01-04"]})
    with pytest.raises(TypeError, match="must be pl.Date"):
        xcals.align_trade_date(bad_df)


def test_align_trade_date_avoids_column_collision(tmp_path, monkeypatch):
    """Bug fix: _xcals_row_idx column name no longer conflicts with user data."""
    package_file = tmp_path / ".xcals"
    local_file = tmp_path / "home" / ".xcals"
    _write_calendar(package_file, _sample_calendar_rows())

    monkeypatch.setattr(_constants, "PACKAGE_XCALS", package_file)
    monkeypatch.setattr(_constants, "FILE_PATH", local_file)

    calendar = _store.Calendar()
    monkeypatch.setattr(xcals.calendar, "CALENDAR", calendar)

    df = pl.DataFrame(
        {
            "date": [datetime.date(2024, 1, 4)],
            "value": [1],
            "_xcals_row_idx": [99],  # would crash old code
        }
    )
    result = xcals.align_trade_date(df)
    assert "trade_date" in result.columns
    assert result["trade_date"].to_list() == [datetime.date(2024, 1, 3)]


def test_calendar_initializes_without_io(tmp_path, monkeypatch):
    """Bug fix: Calendar() construction does not trigger file I/O."""
    missing = tmp_path / "nonexistent" / ".xcals"
    monkeypatch.setattr(_constants, "FILE_PATH", missing)
    monkeypatch.setattr(_constants, "PACKAGE_XCALS", missing)

    cal = _store.Calendar()  # must succeed — lazy loading
    assert cal._ready is False


def test_calendar_raises_on_missing_file(tmp_path, monkeypatch):
    """Bug fix: lazy access gives a clear error when no file is available."""
    missing = tmp_path / "nonexistent" / ".xcals"
    monkeypatch.setattr(_constants, "FILE_PATH", missing)
    monkeypatch.setattr(_constants, "PACKAGE_XCALS", missing)

    cal = _store.Calendar()
    with pytest.raises((FileNotFoundError, RuntimeError)):
        cal.is_tradeday("2024-01-02")


def test_update_preserves_original_on_bad_download(tmp_path, monkeypatch):
    """Bug fix: update() with invalid schema does not corrupt the local file."""
    package_file = tmp_path / "package" / ".xcals"
    local_file = tmp_path / "home" / ".xcals"
    package_file.parent.mkdir(parents=True, exist_ok=True)
    _write_calendar(package_file, _sample_calendar_rows())

    monkeypatch.setattr(_constants, "FILE_PATH", local_file)
    monkeypatch.setattr(_constants, "PACKAGE_XCALS", package_file)

    cal = _store.Calendar()
    cal.reload()
    original_bytes = local_file.read_bytes()

    def bad_download(target_path=None):
        dest = target_path or _constants.FILE_PATH
        pl.DataFrame({"bad_col": [1]}).write_parquet(dest)

    monkeypatch.setattr(_io, "download_calendar_table", bad_download)

    with pytest.raises(ValueError, match="Missing required columns"):
        cal.update()

    # Original file untouched
    assert local_file.read_bytes() == original_bytes


def test_failed_reload_retries_on_access(tmp_path, monkeypatch):
    """Bug fix: after a failed load, fixing the environment allows retry."""
    missing = tmp_path / "nonexistent" / ".xcals"
    monkeypatch.setattr(_constants, "FILE_PATH", missing)
    monkeypatch.setattr(_constants, "PACKAGE_XCALS", missing)

    cal = _store.Calendar()

    with pytest.raises((FileNotFoundError, RuntimeError)):
        cal.is_tradeday("2024-01-02")

    # Fix environment: provide valid file
    valid = tmp_path / "valid" / ".xcals"
    valid.parent.mkdir(parents=True, exist_ok=True)
    _write_calendar(valid, _sample_calendar_rows())
    monkeypatch.setattr(_constants, "PACKAGE_XCALS", valid)
    monkeypatch.setattr(_constants, "FILE_PATH", valid)

    # Retry succeeds — not stale, not empty
    assert cal.is_tradeday("2024-01-02") is True
    assert cal.is_tradeday("2024-01-01") is False


def test_read_calendar_table_clear_error_when_both_missing(tmp_path, monkeypatch):
    """Bug fix: when both local and packaged files are absent, get RuntimeError."""
    missing = tmp_path / "nonexistent" / ".xcals"
    monkeypatch.setattr(_constants, "FILE_PATH", missing)
    monkeypatch.setattr(_constants, "PACKAGE_XCALS", missing)

    with pytest.raises(RuntimeError):
        _io.read_calendar_table()


def test_get_previous_report_dates_returns_scalar_for_single_result():
    assert xcals.get_previous_report_dates("2024-10-15", n=1) == "2024-09-30"
    assert xcals.get_previous_report_dates("2024-10-15", n=1, to_str=False) == datetime.date(
        2024, 9, 30
    )
