# xcals Calendar Redesign

## Goal

Modernize `xcals` internals while keeping the public API stable.

The current implementation uses a plain-text list of trading days as its only
source of truth. The redesign switches the storage model to a natural-day
calendar table with explicit flags, while preserving existing user-facing
functions such as `get_tradingdays`, `is_tradeday`, `shift_tradeday`, and
`get_last_tradingday`.

## Confirmed Constraints

- Public API stays compatible.
- `Calendar` must load the new natural-day table and cache derived indexes in
  members.
- `Calendar` should not lazy-load data. It must be fully usable after
  initialization.
- The bundled default data file is
  `src/xcals/.xcals.parquet`.
- On first use, the bundled file is copied to the user directory and used as
  the local working copy.
- `update()` remains supported and downloads the same parquet schema from the
  remote source, replacing the local working copy and reloading in-process
  state.
- After validation and migration are complete, the file naming will converge
  back to `.xcals` and fully replace the old text-based format.

## Target Data Model

The new canonical calendar data is a parquet table with this schema:

```python
Schema(
    [
        ("date", Date),
        ("IfTradingDay", Int64),
        ("IfWeekEnd", Int64),
        ("IfMonthEnd", Int64),
        ("IfQuarterEnd", Int64),
        ("IfYearEnd", Int64),
    ]
)
```

This natural-day table becomes the only persistent source of truth. Trading-day
lists and other convenient lookup structures are runtime-derived caches, not
separate persisted models.

## Architecture

### Storage Layer

`src/xcals/_store.py` becomes a narrow storage utility module. It is
responsible for:

- Defining canonical paths and URLs
- Ensuring a local working copy exists
- Copying the bundled package file to the user directory on first use
- Reading the parquet calendar table
- Validating schema and required columns
- Downloading updated parquet data into the local working copy

It is not responsible for query semantics, date shifting, or derived lookup
behavior.

### Calendar Core

`Calendar` remains the single internal stateful object. There is no separate
`CalendarData` abstraction.

`Calendar.__init__()` performs the full initialization flow:

1. Ensure the user-local calendar file exists
2. Read the parquet table
3. Validate schema
4. Sort and normalize data as needed
5. Build cached runtime indexes

Required cached members:

- `self._table`: full natural-day table sorted by `date`
- `self._trading_days`: ordered trading-day list
- `self._trading_day_set`: trading-day membership set

Optional cached members may be added only when they serve a concrete internal
use case. End-of-period flags already exist in the table, so separate cached
lists for month-end, quarter-end, or year-end should be introduced only if a
measured use case appears.

`Calendar.reload()` reruns the same loading pipeline and rebuilds all cached
members.

`Calendar.update()` downloads the latest parquet file through the storage layer
and immediately calls `reload()`.

### Public API Layer

`src/xcals/calendar.py` remains the public module API surface.

It continues to expose module-level functions that delegate to the process-wide
`CALENDAR` instance.

`get_previous_report_dates(...)` remains independent from the calendar storage
model. It is based on report-date rules rather than exchange trading-day data,
so it should not be forced into the new table-backed `Calendar` internals.

## API Mapping

### `get_tradingdays`

Behavior stays unchanged.

Internally, this can be implemented either by filtering the natural-day table on
`IfTradingDay == 1` within the requested date range, or by slicing the cached
trading-day list. The recommended implementation is to use the cached ordered
trading-day list for the returned sequence because it keeps semantics simple and
avoids repeated frame filtering for a hot path.

Return types remain:

- `list[str]` when `to_str=True`
- `list[datetime.date]` when `to_str=False`

### `is_tradeday`

Behavior stays unchanged.

Implementation should use `self._trading_day_set` for constant-time membership
checks.

### `get_last_tradingday`

Behavior stays unchanged.

Implementation should continue to use ordered trading-day indexes with
`bisect`, since the problem is positional rather than relational.

### `shift_tradeday`

Behavior stays unchanged, including the current rules for non-trading-day input:

- `num > 0`: shift forward starting from the next trading day when the input is
  not a trading day
- `num < 0`: shift backward starting from the previous trading day when the
  input is not a trading day
- `num == 0`: return the original date unchanged

Implementation should continue to use the cached ordered trading-day list with
`bisect`. The new natural-day table improves storage quality, but it does not
justify replacing a simple and stable index-based algorithm here.

### `update`

Behavior stays unchanged from the user perspective: refresh local calendar data
and make it immediately available.

The storage format changes from the old plain-text file to the new parquet file.

## Storage and Path Conventions

Initial migration phase:

- Bundled package file:
  `src/xcals/.xcals.parquet`
- User-local working copy:
  `~/.xcals.parquet`

Final naming convergence after migration validation:

- Bundled package file:
  `src/xcals/.xcals`
- User-local working copy:
  `~/.xcals`

The implementation should centralize these paths as constants so the later file
rename is a small targeted change rather than a behavioral rewrite.

## Modernization Rules

The redesign should also normalize the implementation style:

- Use `pathlib.Path` instead of `os.path`
- Replace implicit column assumptions with explicit schema and column constants
- Remove `_initialized` and `_ensure_loaded()` lifecycle tricks
- Make reload behavior explicit
- Keep storage code and query semantics separate
- Keep module-level API as thin wrappers over `Calendar`

The goal is not to over-abstract the module. `xcals` is still a small package,
so modernization should improve clarity without introducing extra internal
layers that do not pay for themselves.

## Testing Plan

Coverage should expand from smoke tests to behavioral contract tests.

Required tests:

- First-time initialization copies the bundled file to the user directory
- Parquet schema validation succeeds for the expected file
- Schema validation fails with a clear error when required columns are missing
- `get_tradingdays` preserves current behavior and return types
- `is_tradeday` preserves current behavior
- `get_last_tradingday` preserves current behavior
- `shift_tradeday` preserves current behavior for:
  - trading-day input
  - non-trading-day input
  - positive offsets
  - negative offsets
  - zero offset
- `update()` replaces local data and reloads cached state

Tests should avoid coupling to the real user home directory by patching the
working-copy path in the storage layer.

## Migration Sequence

1. Introduce parquet-backed storage helpers in `_store.py`
2. Refactor `Calendar` to initialize eagerly from the new storage layer
3. Rebuild existing public methods on top of cached indexes derived from the
   parquet table
4. Expand tests to cover initialization, schema validation, and behavior
   preservation
5. Keep public API unchanged throughout
6. After the implementation is stable, rename the working file convention from
   `.xcals.parquet` to `.xcals` without changing semantics

## Risks and Non-Goals

### Risks

- File-format migration can accidentally break first-use initialization if the
  bundled-file copy path is not tested carefully.
- If date values are inconsistently represented as strings versus `date`
  objects, edge-case regressions may appear in offset and lookup operations.
- The final `.xcals.parquet` to `.xcals` rename can create avoidable churn if
  path constants are not centralized from the start.

### Non-Goals

- Changing the public API
- Rewriting report-date logic into table-driven calendar logic
- Introducing extra data-holder abstractions such as `CalendarData`
- Generalizing `xcals` into a broad calendar framework beyond current needs
