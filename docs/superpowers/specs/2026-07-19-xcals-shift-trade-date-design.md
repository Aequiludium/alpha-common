# xcals DataFrame Trade-Date Shift Design

## Goal

Add a vectorized `xcals.shift_trade_date` API that shifts every value in a Polars
`Date` column by a fixed number of trading days. The API follows the existing
`align_trade_date` DataFrame interface: it preserves the input rows and source
column, then appends a configurable result column.

## Public API

`shift_trade_date(df: pl.DataFrame, date_col: str = "date", num: int = 1,
trade_date_col: str = "trade_date") -> pl.DataFrame`

The function is exported from `xcals.__init__`.

Validation matches `align_trade_date` where applicable:

- `date_col` must exist and have type `pl.Date`.
- `num` must be an integer; booleans are rejected.
- `trade_date_col` must be distinct from `date_col` and absent from the input.

## Shift Semantics

- `num > 0`: anchor on the first trading day on or after the input date, then
  shift forward by `num` trading days.
- `num < 0`: anchor on the first trading day on or before the input date, then
  shift backward by `abs(num)` trading days.
- `num == 0`: copy the original date without aligning non-trading dates.
- Null input dates and shifts outside the available calendar produce null.
- Input row order and all existing columns are preserved.

These rules reproduce the existing scalar `shift_tradeday` behavior for dates
inside the calendar, while using nullable column results instead of aborting the
whole DataFrame when an individual row is out of range.

## Implementation

Add a `Calendar.shift_trade_date` method in `src/xcals/_store.py`. For nonzero
offsets, build a sorted trading-date mapping whose result column is created with
a Polars column `shift(-num)`. Join the input dates to this mapping with
`join_asof`: use `forward` for positive offsets and `backward` for negative
offsets. A temporary UUID-based row-index column restores the original order
without colliding with user columns.

The public wrapper in `src/xcals/calendar.py` performs argument validation and
delegates to the calendar instance. Zero offset uses a direct column copy and
does not require calendar lookup.

## Testing

Extend `tests/test_xcals_calendar.py` with cases covering:

- positive and negative shifts from trading and non-trading dates;
- zero offset, null values, and dates beyond calendar coverage;
- original row order and source-column preservation;
- missing or non-`Date` input columns, invalid `num`, and output-column
  collisions;
- top-level import/export of `shift_trade_date`.

Run pytest and both Ruff checks before completion.
