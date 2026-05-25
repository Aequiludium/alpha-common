import datetime

import xcals


def test_get_previous_report_dates_returns_scalar_for_single_result():
    assert xcals.get_previous_report_dates("2024-10-15", n=1) == "2024-09-30"
    assert xcals.get_previous_report_dates("2024-10-15", n=1, to_str=False) == datetime.date(
        2024, 9, 30
    )
