# ygo Top History and Sorting Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add actual task-group start times, typed header sorting, newest-first ordering, and persistent history for the latest 100 completed groups to `ygo top`.

**Architecture:** Workers report monotonic and Unix timestamps through the existing result channel. The publisher keeps live state in shared memory and atomically archives terminal groups as independent JSON records; the monitor flattens and deduplicates live plus historical groups, while the Textual table renders sortable typed cells without remounting.

**Tech Stack:** Python 3.11+, joblib, Textual `DataTable`, platformdirs, JSON, pytest, Ruff, uv.

---

## File Responsibilities

- Create `src/ygo/telemetry/history.py`: completed-group record model and private atomic JSON store.
- Modify `src/ygo/_pool.py`: capture and forward Unix start/finish timestamps.
- Modify `src/ygo/telemetry/model.py`: add optional registration/start/finish wall-clock fields.
- Modify `src/ygo/telemetry/publisher.py`: track wall-clock fields and archive terminal groups once.
- Modify `src/ygo/monitor.py`: flatten, merge, and deduplicate live and historical tasks.
- Modify `src/ygo/tui.py`: render `STARTED`, use typed cells, and sort from header clicks.
- Modify `README.md`: document history retention and sorting controls.
- Add/modify focused tests under `tests/ygo/`.

### Task 1: Propagate Wall-Clock Task Times

**Files:**
- Modify: `src/ygo/_pool.py:26-116`
- Modify: `src/ygo/_pool.py:268-284`
- Modify: `src/ygo/telemetry/model.py:10-20`
- Modify: `src/ygo/telemetry/model.py:89-104`
- Modify: `tests/ygo/test_model.py`
- Modify: `tests/ygo/test_pool_monitoring.py`

- [ ] **Step 1: Write failing model and callback tests**

Extend the model round-trip fixture:

```python
GroupSnapshot(
    id="quote",
    status="done",
    total=10,
    completed=10,
    failed=0,
    started_monotonic=20.0,
    finished_monotonic=25.0,
    registered_at=1000.0,
    started_at=1001.0,
    finished_at=1006.0,
)
```

Remove the three new keys from serialized JSON and assert decoding matches a
copy of the snapshot whose three new fields are `None`, proving schema-1
readers accept older snapshots:

```python
payload = json.loads(snapshot.to_json())
group_payload = payload["pools"][0]["groups"][0]
for field in ("registered_at", "started_at", "finished_at"):
    del group_payload[field]
expected = replace(
    snapshot,
    pools=(
        replace(
            snapshot.pools[0],
            groups=(
                replace(
                    snapshot.pools[0].groups[0],
                    registered_at=None,
                    started_at=None,
                    finished_at=None,
                ),
            ),
        ),
    ),
)
assert ProcessSnapshot.from_json(json.dumps(payload)) == expected
```

Change `FakePublisher.record_completion()` to receive
`started_at`/`finished_at`, store all four timestamps, and assert:

```python
assert all(
    started_monotonic <= finished_monotonic and started_at <= finished_at
    for _, _, _, started_monotonic, finished_monotonic, started_at, finished_at
    in publisher.completions
)
```

- [ ] **Step 2: Run the focused tests and verify red**

Run:

```bash
uv run pytest tests/ygo/test_model.py tests/ygo/test_pool_monitoring.py -q
```

Expected: failures because `GroupSnapshot` and the pool callback do not expose
wall-clock timestamps.

- [ ] **Step 3: Add optional snapshot timestamps**

Add fields after the existing timing fields:

```python
registered_at: float | None = None
started_at: float | None = None
finished_at: float | None = None
```

Decode each with a shared helper:

```python
def _optional_float(value: object) -> float | None:
    return None if value is None else float(value)
```

Keep `SCHEMA_VERSION = 1`.

- [ ] **Step 4: Capture Unix timestamps in workers**

Change `run_job()` to capture both clocks:

```python
started_at = time.time()
started_monotonic = time.monotonic()
try:
    result = job()
    finished_monotonic = time.monotonic()
    finished_at = time.time()
    return (
        task_name,
        result,
        False,
        None,
        started_monotonic,
        finished_monotonic,
        started_at,
        finished_at,
    )
except Exception as exc:
    finished_monotonic = time.monotonic()
    finished_at = time.time()
    error = f"{type(exc).__name__}: {exc}"
    return (
        task_name,
        None,
        True,
        error,
        started_monotonic,
        finished_monotonic,
        started_at,
        finished_at,
    )
```

Expand `completion_callback` and the `Pool.do()` publisher call with the two
Unix timestamps.

- [ ] **Step 5: Run focused tests and commit**

Run:

```bash
uv run pytest tests/ygo/test_model.py tests/ygo/test_pool_monitoring.py -q
uv run ruff check src/ygo/_pool.py src/ygo/telemetry/model.py tests/ygo/test_model.py tests/ygo/test_pool_monitoring.py
```

Expected: all selected tests pass.

Commit:

```bash
git add src/ygo/_pool.py src/ygo/telemetry/model.py tests/ygo/test_model.py tests/ygo/test_pool_monitoring.py
git commit -m "feat(ygo): capture task wall-clock times"
```

### Task 2: Implement the Atomic History Store

**Files:**
- Create: `src/ygo/telemetry/history.py`
- Create: `tests/ygo/test_history.py`

- [ ] **Step 1: Write failing history-store tests**

Create a reusable record:

```python
def make_record(index: int) -> HistoryRecord:
    return HistoryRecord(
        task_key=f"42:1000000000:pool:{index}",
        pid=42,
        process_started_at=1.0,
        pool_id="pool",
        group_id=f"group-{index}",
        command="python sync.py",
        status="done",
        total=10,
        completed=10,
        failed=0,
        last_error=None,
        log_path=None,
        registered_at=1000.0 + index,
        started_at=1001.0 + index,
        finished_at=1006.0 + index,
        elapsed_seconds=5.0,
        rate=2.0,
    )
```

Add tests that:

- append and round-trip one record;
- overwrite the same `task_key` without duplication;
- append 105 records and retain `group-104` through `group-5`;
- ignore a malformed `.json` file;
- verify directory mode `0o700` and record mode `0o600` on non-Windows;
- honor `YGO_HISTORY_DIR`.

Also test the shared key helper:

```python
assert make_task_key(42, 1.5, "pool", "group", 2.5) == (
    '[42,1500000000,"pool","group",2500000000]'
)
```

- [ ] **Step 2: Run the tests and verify red**

Run:

```bash
uv run pytest tests/ygo/test_history.py -q
```

Expected: collection fails because `ygo.telemetry.history` does not exist.

- [ ] **Step 3: Implement `HistoryRecord`**

Use a frozen dataclass with explicit JSON validation:

```python
@dataclass(frozen=True, slots=True)
class HistoryRecord:
    task_key: str
    pid: int
    process_started_at: float
    pool_id: str
    group_id: str
    command: str
    status: str
    total: int
    completed: int
    failed: int
    last_error: str | None
    log_path: str | None
    registered_at: float
    started_at: float
    finished_at: float
    elapsed_seconds: float
    rate: float
    schema_version: int = 1

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False, separators=(",", ":"), sort_keys=True)

    @classmethod
    def from_json(cls, value: str) -> HistoryRecord:
        try:
            payload = json.loads(value)
            if payload.get("schema_version") != 1:
                raise ValueError("unsupported history schema")
            last_error = payload.get("last_error")
            log_path = payload.get("log_path")
            return cls(
                task_key=str(payload["task_key"]),
                pid=int(payload["pid"]),
                process_started_at=float(payload["process_started_at"]),
                pool_id=str(payload["pool_id"]),
                group_id=str(payload["group_id"]),
                command=str(payload["command"]),
                status=str(payload["status"]),
                total=int(payload["total"]),
                completed=int(payload["completed"]),
                failed=int(payload["failed"]),
                last_error=None if last_error is None else str(last_error),
                log_path=None if log_path is None else str(log_path),
                registered_at=float(payload["registered_at"]),
                started_at=float(payload["started_at"]),
                finished_at=float(payload["finished_at"]),
                elapsed_seconds=float(payload["elapsed_seconds"]),
                rate=float(payload["rate"]),
            )
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            raise ValueError("invalid ygo history record") from exc
```

All required numeric values must be converted with `int()`/`float()` and
malformed payloads must raise `ValueError`.

- [ ] **Step 4: Implement `HistoryStore`**

Use a hashed stable filename and atomic replacement:

```python
HISTORY_LIMIT = 100

def make_task_key(
    pid: int,
    process_started_at: float,
    pool_id: str,
    group_id: str,
    registered_at: float,
) -> str:
    process_identity_ns = int(process_started_at * 1_000_000_000)
    registration_ns = int(registered_at * 1_000_000_000)
    return json.dumps(
        [pid, process_identity_ns, pool_id, group_id, registration_ns],
        ensure_ascii=False,
        separators=(",", ":"),
    )

class HistoryStore:
    def __init__(self, root: str | Path | None = None):
        configured = os.environ.get("YGO_HISTORY_DIR")
        self.root = Path(root or configured or user_state_path("ygo") / "history")

    def append(self, record: HistoryRecord) -> None:
        self._ensure_root()
        digest = hashlib.sha256(record.task_key.encode("utf-8")).hexdigest()
        target = self.root / f"{digest}.json"
        temporary = self.root / f".{digest}.{uuid.uuid4().hex}.tmp"
        temporary.write_text(record.to_json(), encoding="utf-8")
        _chmod(temporary, 0o600)
        temporary.replace(target)
        self._prune(HISTORY_LIMIT)

    def recent(self, limit: int = HISTORY_LIMIT) -> list[HistoryRecord]:
        records = self._read_valid()
        records.sort(key=lambda item: (item.finished_at, item.task_key), reverse=True)
        self._remove_records(records[limit:])
        return records[:limit]
```

Create the directory with `0o700`. Ignore unreadable or malformed records.
Pruning removes only valid records beyond the requested limit.

- [ ] **Step 5: Run focused tests and commit**

Run:

```bash
uv run pytest tests/ygo/test_history.py -q
uv run ruff check src/ygo/telemetry/history.py tests/ygo/test_history.py
```

Expected: all history tests pass.

Commit:

```bash
git add src/ygo/telemetry/history.py tests/ygo/test_history.py
git commit -m "feat(ygo): persist completed task groups"
```

### Task 3: Archive Terminal Groups from the Publisher

**Files:**
- Modify: `src/ygo/telemetry/publisher.py:20-233`
- Modify: `tests/ygo/test_publisher.py`
- Modify: `tests/ygo/test_end_to_end.py`

- [ ] **Step 1: Write failing publisher-history tests**

Add a `FakeHistory` with `records` and `append()`. Construct the publisher with
deterministic monotonic and wall clocks:

```python
publisher = TelemetryPublisher(
    transport=transport,
    history=history,
    clock=FakeClock(100.0),
    wall_clock=FakeClock(1000.0),
    start_thread=False,
)
```

Assert registration publishes `registered_at == 1000.0`. Complete a two-result
group with starts `1001.0` and `1002.0`, finishes `1004.0` and `1006.0`, then
assert exactly one archived record with:

```python
assert record.started_at == 1001.0
assert record.finished_at == 1006.0
assert record.elapsed_seconds == 5.0
assert record.rate == 0.4
```

Add a failing history writer and assert the live snapshot still reaches the
transport and task execution remains unaffected.

- [ ] **Step 2: Run publisher tests and verify red**

Run:

```bash
uv run pytest tests/ygo/test_publisher.py -q
```

Expected: failures because the publisher has no history or wall-clock support.

- [ ] **Step 3: Track wall-clock state**

Extend `_GroupState`:

```python
registered_at: float
started_at: float | None = None
finished_at: float | None = None
archived: bool = False
```

Add `history` and `wall_clock` constructor dependencies. Set `registered_at`
when registering the pool, advancing equal or backward readings minimally so
repeated executions keep distinct task keys. On each completion, keep the
earliest start and latest finish for both clock families.

- [ ] **Step 4: Archive exactly once at terminal transition**

When `completed >= total`, set terminal status and call a private method only
when `archived` is false:

```python
def _archive_group(self, pool: _PoolState, group: _GroupState) -> None:
    if (
        group.started_at is None
        or group.finished_at is None
        or group.started_monotonic is None
        or group.finished_monotonic is None
    ):
        return
    elapsed = max(0.0, group.finished_monotonic - group.started_monotonic)
    record = HistoryRecord(
        task_key=make_task_key(
            self._pid,
            self._process_started_at,
            pool.id,
            group.id,
            group.registered_at,
        ),
        pid=self._pid,
        process_started_at=self._process_started_at,
        pool_id=pool.id,
        group_id=group.id,
        command=self._command,
        status=group.status,
        total=group.total,
        completed=group.completed,
        failed=group.failed,
        last_error=group.last_error,
        log_path=self._log_path,
        registered_at=group.registered_at,
        started_at=group.started_at,
        finished_at=group.finished_at,
        elapsed_seconds=elapsed,
        rate=group.completed / elapsed if elapsed else 0.0,
    )
    try:
        self._history.append(record)
    except Exception as exc:
        self._warn_history_once(f"ygo history unavailable: {exc}")
    else:
        group.archived = True
```

History failure must not set `_disabled`; live shared-memory publishing
continues. `complete_pool()` must not archive pending or incomplete groups.

- [ ] **Step 5: Extend end-to-end persistence coverage**

Set `YGO_HISTORY_DIR` to a temporary directory in the subprocess test. After
the producer exits and the runtime registry is empty, assert:

```python
records = HistoryStore(history_dir).recent()
assert len(records) == 1
assert records[0].group_id == "quote"
assert records[0].status == "done"
```

- [ ] **Step 6: Run focused tests and commit**

Run:

```bash
uv run pytest tests/ygo/test_publisher.py tests/ygo/test_end_to_end.py -q
uv run ruff check src/ygo/telemetry/publisher.py tests/ygo/test_publisher.py tests/ygo/test_end_to_end.py
```

Expected: all selected tests pass.

Commit:

```bash
git add src/ygo/telemetry/publisher.py tests/ygo/test_publisher.py tests/ygo/test_end_to_end.py
git commit -m "feat(ygo): archive terminal group telemetry"
```

### Task 4: Merge Live and Historical Monitor State

**Files:**
- Modify: `src/ygo/monitor.py`
- Modify: `tests/ygo/test_monitor.py`

- [ ] **Step 1: Write failing merge and deduplication tests**

Define a live process and a historical record with the same task key. Assert
`read_monitor_state()` returns the live form only. Add a second historical
record and assert it remains. Verify the live task key contains process start
identity, pool ID, and group ID.

The expected domain types are:

```python
@dataclass(frozen=True, slots=True)
class MonitoredTask:
    key: str
    pid: int
    status: str
    completed: int
    total: int
    failed: int
    registered_at: float
    started_at: float | None
    finished_at: float | None
    started_monotonic: float | None
    finished_monotonic: float | None
    elapsed_seconds: float | None
    rate: float | None
    group_id: str
    command: str
    error: str | None
    log_path: str | None

@dataclass(frozen=True, slots=True)
class MonitorState:
    tasks: tuple[MonitoredTask, ...]
    generation: object
```

- [ ] **Step 2: Run monitor tests and verify red**

Run:

```bash
uv run pytest tests/ygo/test_monitor.py -q
```

Expected: import failure because `MonitoredTask`, `MonitorState`, and
`read_monitor_state` do not exist.

- [ ] **Step 3: Add task-key and flattening helpers**

Import and use the shared helper from `telemetry.history`:

```python
from .telemetry.history import HistoryStore, make_task_key
```

Flatten every live group into `MonitoredTask`. Use `group.registered_at` when it
is not `None`, otherwise fall back to `process.snapshot.process_started_at` for
backward compatibility with old producers. Pass that same timestamp into the
shared task-key helper.

- [ ] **Step 4: Merge history with live state**

Implement `read_monitor_state()` with injectable registry and history:

```python
def read_monitor_state(
    registry: RuntimeRegistry | None = None,
    history: HistoryStore | None = None,
) -> MonitorState:
    live_processes = read_live_snapshots(registry)
    history_records = (history or HistoryStore()).recent()
    tasks = {record.task_key: _historical_task(record) for record in history_records}
    for process in live_processes:
        for task in _live_tasks(process):
            tasks[task.key] = task
    generation = (
        tuple((item.snapshot.pid, item.generation) for item in live_processes),
        tuple((item.task_key, item.finished_at) for item in history_records),
    )
    return MonitorState(tuple(tasks.values()), generation)
```

This function is new; keep `read_live_snapshots()` unchanged so `ygo ps`,
`show`, and `errors` remain live-only.

- [ ] **Step 5: Run focused tests and commit**

Run:

```bash
uv run pytest tests/ygo/test_monitor.py -q
uv run ruff check src/ygo/monitor.py tests/ygo/test_monitor.py
```

Expected: all monitor tests pass.

Commit:

```bash
git add src/ygo/monitor.py tests/ygo/test_monitor.py
git commit -m "feat(ygo): merge live and historical tasks"
```

### Task 5: Add Started Column and Typed Header Sorting

**Files:**
- Modify: `src/ygo/tui.py`
- Modify: `tests/ygo/test_tui.py`

- [ ] **Step 1: Write failing row-rendering tests**

Replace process fixtures with `MonitoredTask` fixtures and test:

```python
row = row_from_task(
    make_task(started_at=1760000000.0, registered_at=1759999999.0),
    now=100.0,
)
assert row.cells["started"].text == datetime.fromtimestamp(
    1760000000.0
).strftime("%Y-%m-%d %H:%M:%S")
```

For a pending task, assert display text is `--` and the `STARTED` sort value is
its registration timestamp. Retain the existing terminal rate/elapsed freezing
tests.

- [ ] **Step 2: Write failing typed-cell and sort-state tests**

Define expected sortable cells:

```python
@dataclass(frozen=True, slots=True)
class TableCell:
    text: str
    sort_value: int | float | str

    def __rich__(self) -> str:
        return self.text
```

Test that progress `9/10` sorts after `10/100`, numeric PID `20` sorts before
`100`, and start times sort by epoch rather than formatted text.

Use `app.run_test()` to click or post `DataTable.HeaderSelected` and verify:

- initial order is newest first;
- selecting `PID` sorts ascending;
- selecting `PID` again sorts descending;
- a newly added task moves to the top under the default sort;
- changing one counter keeps the same `DataTable` instance.

- [ ] **Step 3: Run TUI tests and verify red**

Run:

```bash
uv run pytest tests/ygo/test_tui.py -q
```

Expected: failures because `STARTED`, typed cells, and header sorting are absent.

- [ ] **Step 4: Render typed cells**

Insert the column:

```python
COLUMNS = (
    ("pid", "PID"),
    ("status", "STATUS"),
    ("progress", "PROGRESS"),
    ("rate", "RATE"),
    ("failed", "FAIL"),
    ("elapsed", "ELAPSED"),
    ("started", "STARTED"),
    ("group", "GROUP"),
    ("command", "COMMAND"),
)
```

Make `MonitorRow.cells` a `dict[str, TableCell]`. Use numeric values for numeric
columns, completion ratio for progress, case-folded values for text, and
`started_at or registered_at` for start sorting. Use `datetime.fromtimestamp()`
for local-time rendering.

Change the application provider to the merged monitor surface:

```python
def __init__(
    self,
    *,
    provider: Callable[[], MonitorState] = read_monitor_state,
):
    super().__init__()
    self._provider = provider
    self._reconciler: TableReconciler | None = None
    self._rows: dict[str, MonitorRow] = {}
    self._sort_column = "started"
    self._sort_reverse = True

def refresh_monitor(self) -> None:
    if self._reconciler is None:
        return
    now = time.monotonic()
    state = self._provider()
    rows = [row_from_task(task, now=now) for task in state.tasks]
    generation = (state.generation, int(now * 2))
    result = self._reconciler.apply(rows, generation=generation)
    self._rows = {row.key: row for row in rows}
    if result.structure_changed or self._sort_column in result.changed_columns:
        self._sort_table()
```

- [ ] **Step 5: Return reconciliation changes**

Have `TableReconciler.apply()` return:

```python
@dataclass(frozen=True, slots=True)
class ReconcileResult:
    structure_changed: bool
    changed_columns: frozenset[str]
```

Record added/removed rows as structural changes and updated cells by column.
Continue calling only `add_row`, `remove_row`, and `update_cell`.

- [ ] **Step 6: Implement default and header sorting**

Default state:

```python
self._sort_column = "started"
self._sort_reverse = True
```

Handle header selection:

```python
def on_data_table_header_selected(self, event: DataTable.HeaderSelected) -> None:
    selected = str(event.column_key.value)
    if selected == self._sort_column:
        self._sort_reverse = not self._sort_reverse
    else:
        self._sort_column = selected
        self._sort_reverse = False
    self._sort_table()
```

Sort typed cells:

```python
table.sort(
    self._sort_column,
    key=lambda cell: cell.sort_value,
    reverse=self._sort_reverse,
)
```

After reconciliation, sort only if structure changed or the active sort column
changed. This avoids an unconditional full table refresh every 200 ms.

- [ ] **Step 7: Run focused tests and commit**

Run:

```bash
uv run pytest tests/ygo/test_tui.py -q
uv run ruff check src/ygo/tui.py tests/ygo/test_tui.py
```

Expected: all TUI tests pass.

Commit:

```bash
git add src/ygo/tui.py tests/ygo/test_tui.py
git commit -m "feat(ygo): sort top by typed columns"
```

### Task 6: Documentation and Full Verification

**Files:**
- Modify: `README.md:190-201`
- Verify: all changed source and test files

- [ ] **Step 1: Update user documentation**

Document:

```text
ygo top shows every live task group plus the latest 100 completed groups.
Completed history is stored in the platform user-state directory and survives
producer shutdown. STARTED uses local time. Click a column header to sort and
click it again to reverse the direction; the default is newest first.
```

Keep `show_progress=True` unchanged.

- [ ] **Step 2: Run the complete verification chain**

Run:

```bash
uv sync
uv run ruff format .
uv run ruff check .
uv run ruff format --check .
uv run pytest tests/
uv build
git diff --check
```

Expected: Ruff passes, all tests pass, wheel and sdist build successfully, and
the diff has no whitespace errors.

- [ ] **Step 3: Perform a manual terminal smoke test**

Use an isolated state directory:

```bash
export YGO_RUNTIME_DIR="$(mktemp -d)"
export YGO_HISTORY_DIR="$(mktemp -d)"
uv run ygo top
```

In another terminal run a script containing two named groups. Confirm:

- pending rows display `STARTED=--` and appear at the top;
- actual local start time appears after the first result;
- column headers toggle sort direction;
- no full-screen flicker occurs during updates;
- completed rows remain after the producer exits;
- after 105 completed groups only the latest 100 historical rows remain.

- [ ] **Step 4: Commit documentation and final formatting**

Commit:

```bash
git add README.md
git commit -m "docs(ygo): document top history and sorting"
```

- [ ] **Step 5: Re-run final evidence commands**

Run:

```bash
uv run ruff check .
uv run ruff format --check .
uv run pytest tests/
uv build
git status --short
```

Expected: every command succeeds and the worktree is clean.
