"""Tests for alpha-common modules."""


def test_import_xcals():
    import xcals  # noqa: F401


def test_import_blazestore():
    from blazestore import ParquetStore  # noqa: F401


def test_import_ygo():
    from ygo import Pool  # noqa: F401


def test_import_clickhouse_df():
    from clickhouse_df import to_polars  # noqa: F401


def test_xcals_today():
    import xcals

    today = xcals.today()
    assert isinstance(today, str)
    assert len(today) == 10  # YYYY-MM-DD format
