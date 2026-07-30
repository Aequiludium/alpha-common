# ygo Table Content Width Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `ygo top` size sortable cells from their complete terminal text and retain correct widths after incremental updates.

**Architecture:** Keep `TableCell` as the single carrier for display and typed sorting, but implement Rich's measurement protocol with Unicode-aware terminal-cell width. Ask Textual to recompute an auto-width column whenever reconciliation changes a cell, preserving the existing mounted table and horizontal scrolling.

**Tech Stack:** Python 3.11+, Rich, Textual `DataTable`, pytest

---

### Task 1: Report the complete Rich cell width

**Files:**
- Modify: `src/ygo/tui.py`
- Test: `tests/ygo/test_tui.py`

- [ ] **Step 1: Write the failing measurement tests**

Add imports and a regression test:

```python
from rich.console import Console
from textual.render import measure


def test_table_cell_reports_plain_and_wide_terminal_widths():
    console = Console()

    assert measure(console, TableCell("2026-07-30 14:23:45", 0.0), 1) == 19
    assert measure(console, TableCell("开始时间", "开始时间"), 1) == 8
```

- [ ] **Step 2: Run the test and verify red**

Run:

```bash
uv run pytest tests/ygo/test_tui.py::test_table_cell_reports_plain_and_wide_terminal_widths -q
```

Expected: fail because Rich measures each `TableCell` as `1`.

- [ ] **Step 3: Implement Rich measurement**

Add imports and the protocol method:

```python
from rich.cells import cell_len
from rich.console import Console, ConsoleOptions
from rich.measure import Measurement


@dataclass(frozen=True, slots=True)
class TableCell:
    text: str
    sort_value: SortValue

    def __rich__(self) -> str:
        return self.text

    def __rich_measure__(
        self,
        console: Console,
        options: ConsoleOptions,
    ) -> Measurement:
        width = cell_len(self.text)
        return Measurement(width, width)

    def __str__(self) -> str:
        return self.text
```

- [ ] **Step 4: Run the focused test and verify green**

Run:

```bash
uv run pytest tests/ygo/test_tui.py::test_table_cell_reports_plain_and_wide_terminal_widths -q
```

Expected: `1 passed`.

- [ ] **Step 5: Commit the measurement fix**

```bash
git add src/ygo/tui.py tests/ygo/test_tui.py
git commit -m "fix(ygo): measure sortable table cells"
```

### Task 2: Recompute widths during incremental updates

**Files:**
- Modify: `src/ygo/tui.py`
- Test: `tests/ygo/test_tui.py`

- [ ] **Step 1: Make the reconciler test require width updates**

Extend the fake table method and assertion:

```python
def update_cell(self, row_key, column_key, value, *, update_width=False):
    self.calls.append(
        ("update_cell", str(row_key), str(column_key), value, update_width)
    )
```

Update the changed-cell assertion so both calls end in `True`:

```python
assert [
    (call[0], call[1], call[2], call[3].text, call[4])
    for call in table.calls
] == [
    ("update_cell", "task-123", "progress", "5/10", True),
    ("update_cell", "task-123", "rate", "0.5/s", True),
]
```

- [ ] **Step 2: Run the test and verify red**

Run:

```bash
uv run pytest tests/ygo/test_tui.py::test_reconcile_updates_only_changed_cells -q
```

Expected: fail because `update_width` remains `False`.

- [ ] **Step 3: Enable Textual width recomputation**

Change the update call:

```python
self.table.update_cell(
    key,
    column,
    value,
    update_width=True,
)
```

- [ ] **Step 4: Verify initial and updated sizing in the real table**

Extend the existing Textual app test after the table is mounted:

```python
def column_width(table: DataTable, key: str) -> int:
    return next(
        column.content_width
        for column in table.ordered_columns
        if str(column.key.value) == key
    )


assert column_width(table, "started") == 19
assert column_width(table, "group") >= len("long-group-name")
assert column_width(table, "command") >= len("python sync.py")
```

Use `group_id="long-group-name"` for one mounted task. Then update that task to
`group_id="an-even-longer-group-name"` and assert after `pilot.pause()`:

```python
assert column_width(table, "group") >= len("an-even-longer-group-name")
```

- [ ] **Step 5: Run all TUI tests**

Run:

```bash
uv run pytest tests/ygo/test_tui.py -q
```

Expected: all TUI tests pass.

- [ ] **Step 6: Commit incremental width handling**

```bash
git add src/ygo/tui.py tests/ygo/test_tui.py
git commit -m "fix(ygo): resize changed monitor columns"
```

### Task 3: Verify the complete change

**Files:**
- No source changes expected

- [ ] **Step 1: Run repository checks**

```bash
uv run ruff format .
uv run ruff check .
uv run ruff format --check .
uv run pytest tests/
uv build
git diff --check
```

Expected: Ruff succeeds, all tests pass, both distributions build, and the diff
has no whitespace errors.

- [ ] **Step 2: Run a narrow-terminal smoke test**

Launch `uv run ygo top` in an 80-column PTY with representative `STARTED`,
`GROUP`, and `COMMAND` values. Confirm the column content widths match their
full values and the table has a horizontal scroll range instead of truncating
the underlying values.
