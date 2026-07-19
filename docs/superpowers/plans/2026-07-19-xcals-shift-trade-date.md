# xcals DataFrame Trade-Date Shift Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a vectorized `xcals.shift_trade_date` API, upgrade Polars to 1.42.1, and publish alpha-common 0.1.11 through CI.

**Architecture:** The public wrapper validates DataFrame arguments and delegates to the singleton `Calendar`. The calendar implementation builds a trading-date-to-shifted-date mapping with Polars `shift(-num)`, applies a direction-dependent as-of join, and restores original row order.

**Tech Stack:** Python 3.11, Polars, pytest, Ruff, uv

---

## File Structure

- Modify `src/xcals/_store.py`: implement vectorized calendar lookup and shifting.
- Modify `src/xcals/calendar.py`: add the validated public DataFrame wrapper.
- Modify `src/xcals/__init__.py`: export the new public function.
- Modify `tests/test_xcals_calendar.py`: cover semantics, validation, nulls, range, and ordering.
- Modify `tests/test_imports.py`: verify the top-level public export.
- Modify `pyproject.toml`: require Polars 1.42.1 and set package version 0.1.11.
- Modify `uv.lock`: lock Polars 1.42.1 and alpha-common 0.1.11 metadata.

### Task 1: Define Public Behavior with Failing Tests

**Files:**
- Modify: `tests/test_xcals_calendar.py`
- Modify: `tests/test_imports.py`

- [ ] **Step 1: Add behavior and edge-case tests**

Append tests that reuse `_write_calendar`, `_sample_calendar_rows`, and the
autouse singleton reset fixture:

```python
def test_shift_trade_date_supports_positive_negative_and_zero(tmp_path, monkeypatch):
    package_file = tmp_path / ".xcals"
    local_file = tmp_path / "home" / ".xcals"
    _write_calendar(package_file, _sample_calendar_rows())
    monkeypatch.setattr(_constants, "PACKAGE_XCALS", package_file)
    monkeypatch.setattr(_constants, "FILE_PATH", local_file)

    calendar = _store.Calendar()
    df = pl.DataFrame(
        {
            "date": [
                datetime.date(2024, 1, 5),
                datetime.date(2024, 1, 2),
                datetime.date(2024, 1, 4),
                None,
            ],
            "value": [1, 2, 3, 4],
        },
        schema={"date": pl.Date, "value": pl.Int64},
    )

    forward = calendar.shift_trade_date(df, num=1, trade_date_col="forward_date")
    backward = calendar.shift_trade_date(df, num=-1, trade_date_col="backward_date")
    unchanged = calendar.shift_trade_date(df, num=0, trade_date_col="same_date")

    assert forward["forward_date"].to_list() == [
        datetime.date(2024, 1, 8),
        datetime.date(2024, 1, 3),
        datetime.date(2024, 1, 8),
        None,
    ]
    assert backward["backward_date"].to_list() == [
        datetime.date(2024, 1, 3),
        None,
        datetime.date(2024, 1, 2),
        None,
    ]
    assert unchanged["same_date"].to_list() == df["date"].to_list()
    assert forward["value"].to_list() == [1, 2, 3, 4]
    assert forward["date"].to_list() == df["date"].to_list()


def test_shift_trade_date_returns_null_outside_calendar(tmp_path, monkeypatch):
    package_file = tmp_path / ".xcals"
    local_file = tmp_path / "home" / ".xcals"
    _write_calendar(package_file, _sample_calendar_rows())
    monkeypatch.setattr(_constants, "PACKAGE_XCALS", package_file)
    monkeypatch.setattr(_constants, "FILE_PATH", local_file)
    calendar = _store.Calendar()

    df = pl.DataFrame(
        {"date": [datetime.date(2024, 1, 1), datetime.date(2024, 1, 8)]}
    )

    assert calendar.shift_trade_date(df, num=-1)["trade_date"].to_list() == [
        None,
        datetime.date(2024, 1, 5),
    ]
    assert calendar.shift_trade_date(df, num=1)["trade_date"].to_list() == [
        datetime.date(2024, 1, 3),
        None,
    ]


def test_shift_trade_date_validates_arguments():
    valid = pl.DataFrame({"date": [datetime.date(2024, 1, 2)]})

    with pytest.raises(ValueError, match="Column not found"):
        xcals.shift_trade_date(valid, date_col="missing")
    with pytest.raises(TypeError, match="must be pl.Date"):
        xcals.shift_trade_date(pl.DataFrame({"date": ["2024-01-02"]}))
    with pytest.raises(TypeError, match="num must be an integer"):
        xcals.shift_trade_date(valid, num=1.5)
    with pytest.raises(TypeError, match="num must be an integer"):
        xcals.shift_trade_date(valid, num=True)
    with pytest.raises(ValueError, match="Column already exists"):
        xcals.shift_trade_date(valid, trade_date_col="date")
    with pytest.raises(ValueError, match="Column already exists"):
        xcals.shift_trade_date(
            valid.with_columns(pl.lit(None, dtype=pl.Date).alias("trade_date"))
        )
```

Extend `test_imports.py`:

```python
def test_import_xcals():
    from xcals import shift_trade_date  # noqa: F401
```

- [ ] **Step 2: Run the new tests and confirm RED**

Run:

```bash
uv run pytest \
  tests/test_xcals_calendar.py::test_shift_trade_date_supports_positive_negative_and_zero \
  tests/test_xcals_calendar.py::test_shift_trade_date_returns_null_outside_calendar \
  tests/test_xcals_calendar.py::test_shift_trade_date_validates_arguments \
  tests/test_imports.py::test_import_xcals -v
```

Expected: FAIL because neither `Calendar.shift_trade_date` nor the top-level
`xcals.shift_trade_date` API exists.

- [ ] **Step 3: Commit the failing tests**

```bash
git add tests/test_xcals_calendar.py tests/test_imports.py
git commit -m "test(xcals): define DataFrame trade-date shift behavior"
```

### Task 2: Implement the Calendar Shift

**Files:**
- Modify: `src/xcals/_store.py`

- [ ] **Step 1: Add `Calendar.shift_trade_date`**

Add after `Calendar.shift_tradeday`:

```python
def shift_trade_date(
    self,
    df: pl.DataFrame,
    date_col: str = _constants.DATE_COLUMN,
    num: int = 1,
    trade_date_col: str = "trade_date",
) -> pl.DataFrame:
    """Shift a Date column by a fixed number of trading days."""
    if num == 0:
        return df.with_columns(pl.col(date_col).alias(trade_date_col))

    self._ensure_loaded()
    suffix = uuid.uuid4().hex
    row_idx_col = f"_xcals_row_idx_{suffix}"
    anchor_col = f"_xcals_anchor_date_{suffix}"
    strategy = "forward" if num > 0 else "backward"
    trade_date_map = (
        self._table.filter(pl.col(_constants.TRADING_DAY_COLUMN) == 1)
        .select(pl.col(_constants.DATE_COLUMN).alias(anchor_col))
        .sort(anchor_col)
        .with_columns(pl.col(anchor_col).shift(-num).alias(trade_date_col))
    )

    return (
        df.with_row_index(row_idx_col)
        .sort(date_col)
        .join_asof(
            trade_date_map,
            left_on=date_col,
            right_on=anchor_col,
            strategy=strategy,
        )
        .sort(row_idx_col)
        .drop(row_idx_col, anchor_col)
    )
```

- [ ] **Step 2: Run the two storage behavior tests and confirm GREEN**

Run:

```bash
uv run pytest \
  tests/test_xcals_calendar.py::test_shift_trade_date_supports_positive_negative_and_zero \
  tests/test_xcals_calendar.py::test_shift_trade_date_returns_null_outside_calendar -v
```

Expected: both selected tests PASS, including the null-key assertion.

- [ ] **Step 3: Commit the storage implementation**

```bash
git add src/xcals/_store.py
git commit -m "feat(xcals): vectorize trade-date shifting"
```

### Task 3: Add Validation and Public Export

**Files:**
- Modify: `src/xcals/calendar.py`
- Modify: `src/xcals/__init__.py`

- [ ] **Step 1: Add the validated wrapper**

Add after scalar `shift_tradeday`:

```python
def shift_trade_date(
    df: pl.DataFrame,
    date_col: str = "date",
    num: int = 1,
    trade_date_col: str = "trade_date",
) -> pl.DataFrame:
    """Shift a Polars Date column by a fixed number of trading days."""
    if date_col not in df.columns:
        raise ValueError(f"Column not found: {date_col}")
    if df.schema[date_col] != pl.Date:
        raise TypeError(f"Column {date_col!r} must be pl.Date, got {df.schema[date_col]}")
    if isinstance(num, bool) or not isinstance(num, int):
        raise TypeError(f"num must be an integer, got {type(num).__name__}")
    if trade_date_col in df.columns:
        raise ValueError(f"Column already exists: {trade_date_col}")
    return CALENDAR.shift_trade_date(
        df,
        date_col=date_col,
        num=num,
        trade_date_col=trade_date_col,
    )
```

Import `shift_trade_date` from `.calendar` and add it to `__all__` in
`src/xcals/__init__.py`.

- [ ] **Step 2: Run focused tests and confirm GREEN**

Run the focused command from Task 1.

Expected: all four selected tests PASS.

- [ ] **Step 3: Commit the public API**

```bash
git add src/xcals/calendar.py src/xcals/__init__.py
git commit -m "feat(xcals): expose DataFrame trade-date shift"
```

### Task 4: Upgrade Polars and Prepare Version 0.1.11

**Files:**
- Modify: `pyproject.toml`
- Modify: `uv.lock`

- [ ] **Step 1: Update project metadata**

Change these entries in `pyproject.toml`:

```toml
version = "0.1.11"
```

```toml
"polars>=1.42.1",
```

- [ ] **Step 2: Refresh the lock file**

Run:

```bash
uv lock --upgrade-package polars
uv sync
```

Expected: `uv.lock` records Polars and `polars-runtime-32` 1.42.1, and the
installed environment reports Polars 1.42.1.

- [ ] **Step 3: Verify the installed dependency**

Run:

```bash
uv run python -c 'import polars as pl; print(pl.__version__)'
```

Expected: `1.42.1`.

- [ ] **Step 4: Commit dependency and version metadata**

```bash
git add pyproject.toml uv.lock
git commit -m "chore: upgrade polars to 1.42.1 and bump version to 0.1.11"
```

### Task 5: Verify the Complete Change

**Files:**
- Verify all modified source and test files.

- [ ] **Step 1: Run the xcals test module**

Run: `uv run pytest tests/test_xcals_calendar.py -v`

Expected: all xcals tests PASS.

- [ ] **Step 2: Run the complete test suite**

Run: `uv run pytest tests/`

Expected: all tests PASS.

- [ ] **Step 3: Run formatting and lint checks**

Run:

```bash
uv run ruff format --check .
uv run ruff check .
```

Expected: both commands exit successfully with no formatting or lint errors.

- [ ] **Step 4: Review the final diff**

Run: `git diff origin/main...HEAD --check && git status --short`

Expected: no whitespace errors and a clean feature worktree.

- [ ] **Step 5: Build the release artifacts**

Run: `uv build`

Expected: wheel and source distribution for alpha-common 0.1.11 are created.

### Task 6: Publish Through GitHub CI

**Files:**
- No additional local file changes.

- [ ] **Step 1: Push the feature branch**

Run: `git push -u origin codex/xcals-shift-trade-date`

Expected: the remote branch is created at the verified local HEAD.

- [ ] **Step 2: Open and merge a PR after CI passes**

Create a PR targeting `main` with the feature, tests, Polars upgrade, version,
and verification results. Wait for all required checks, then merge the PR.

Expected: the PR is merged and `origin/main` contains the feature commits.

- [ ] **Step 3: Create GitHub Release v0.1.11**

Create a non-draft GitHub Release tagged `v0.1.11` from the merged `main`.

Expected: `.github/workflows/publish.yml` starts from the `release.published`
event.

- [ ] **Step 4: Wait for CI publishing and verify PyPI**

Wait for the publish workflow to complete successfully, then query:

```bash
curl -fsSL https://pypi.org/pypi/alpha-common/0.1.11/json
```

Expected: HTTP success and package metadata for alpha-common 0.1.11.
