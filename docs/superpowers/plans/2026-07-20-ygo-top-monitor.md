# Ygo Top Monitor Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a local, htop-style `ygo top` monitor backed by shared memory and a Textual table that updates only changed cells.

**Architecture:** Each application process owns one telemetry publisher and shared-memory segment. `Pool` reports aggregate group events to that publisher, a private JSON registry enables local discovery, and a separate Textual CLI reads consistent snapshots and applies row/cell diffs. Inline progress remains enabled by default but becomes a compact single-row summary.

**Tech Stack:** Python 3.11+, `multiprocessing.shared_memory`, JSON/CRC32/`struct`, psutil, platformdirs, Textual 8, joblib, Rich, pytest, Ruff, uv.

---

## File Map

- Create `src/ygo/telemetry/model.py`: immutable snapshot models and JSON conversion.
- Create `src/ygo/telemetry/shared.py`: double-buffer shared-memory protocol.
- Create `src/ygo/telemetry/registry.py`: private runtime registry and process validation.
- Create `src/ygo/telemetry/publisher.py`: process singleton, coalescing, heartbeat, no-throw facade.
- Create `src/ygo/telemetry/__init__.py`: internal telemetry exports.
- Create `src/ygo/monitor.py`: discover and read live process snapshots.
- Create `src/ygo/tui.py`: Textual app and cell-level table reconciliation.
- Create `src/ygo/cli.py`: `top`, `ps`, `show`, `errors`, and `run`.
- Modify `src/ygo/_pool.py`: publish pool/group lifecycle events and use one inline row.
- Modify `src/ygo/progress.py`: support resetting and compact aggregate descriptions.
- Modify `pyproject.toml` and `uv.lock`: dependencies and `ygo` console entry point.
- Modify `README.md`: monitoring and compatibility documentation.
- Create focused tests under `tests/ygo/`.

### Task 1: Dependencies and Snapshot Model

**Files:**
- Modify: `pyproject.toml`
- Modify: `uv.lock`
- Create: `src/ygo/telemetry/__init__.py`
- Create: `src/ygo/telemetry/model.py`
- Test: `tests/ygo/test_model.py`

- [ ] **Step 1: Write the failing model tests**

```python
import pytest

from ygo.telemetry.model import GroupSnapshot, PoolSnapshot, ProcessSnapshot


def test_process_snapshot_round_trip():
    snapshot = ProcessSnapshot(
        pid=123,
        process_started_at=1000.5,
        command="python sync.py",
        cwd="/tmp/work",
        pools=(
            PoolSnapshot(
                id="pool-1",
                backend="threading",
                n_jobs=4,
                status="running",
                groups=(
                    GroupSnapshot(
                        id="quote",
                        status="running",
                        total=10,
                        completed=4,
                        failed=1,
                        started_monotonic=20.0,
                        last_error="timeout",
                    ),
                ),
            ),
        ),
    )

    assert ProcessSnapshot.from_json(snapshot.to_json()) == snapshot


def test_snapshot_rejects_incompatible_schema():
    payload = '{"schema_version": 999, "pid": 1, "process_started_at": 1, "command": "", "cwd": "", "pools": []}'

    with pytest.raises(ValueError, match="schema"):
        ProcessSnapshot.from_json(payload)
```

- [ ] **Step 2: Run the model tests and verify RED**

Run: `uv run pytest tests/ygo/test_model.py -q`

Expected: collection fails because `ygo.telemetry.model` does not exist.

- [ ] **Step 3: Add dependencies and the snapshot model**

Add to `pyproject.toml`:

```toml
dependencies = [
    # existing dependencies remain
    "platformdirs>=4.10.1",
    "psutil>=7.2.2",
    "textual>=8.2.8",
]

[project.scripts]
ygo = "ygo.cli:main"
```

Implement frozen `GroupSnapshot`, `PoolSnapshot`, and `ProcessSnapshot`
dataclasses. `ProcessSnapshot.to_json()` must use compact deterministic JSON;
`from_json()` must validate `schema_version == 1`, normalize nested lists to
tuples, and reject malformed payloads with `ValueError`.

- [ ] **Step 4: Lock dependencies and verify GREEN**

Run:

```bash
uv lock
uv sync
uv run pytest tests/ygo/test_model.py -q
```

Expected: both model tests pass.

- [ ] **Step 5: Commit the model**

```bash
git add pyproject.toml uv.lock src/ygo/telemetry tests/ygo/test_model.py
git commit -m "feat(ygo): add telemetry snapshot model"
```

### Task 2: Consistent Shared-Memory Snapshots

**Files:**
- Create: `src/ygo/telemetry/shared.py`
- Test: `tests/ygo/test_shared.py`

- [ ] **Step 1: Write failing protocol tests**

```python
def test_shared_state_round_trip(snapshot):
    writer = SharedState.create(capacity=4096)
    reader = SharedState.open(writer.name)
    try:
        generation = writer.write(snapshot)
        read = reader.read()
        assert read is not None
        assert read.generation == generation
        assert read.snapshot == snapshot
    finally:
        reader.close()
        writer.close()
        writer.unlink()


def test_reader_rejects_checksum_mismatch(snapshot):
    writer = SharedState.create(capacity=4096)
    try:
        writer.write(snapshot)
        writer.corrupt_active_payload_for_test()
        assert writer.read() is None
    finally:
        writer.close()
        writer.unlink()


def test_overflow_truncates_error_details(oversized_snapshot):
    state = SharedState.create(capacity=1024)
    try:
        state.write(oversized_snapshot)
        read = state.read()
        assert read.snapshot.telemetry_overflow is True
        assert len(read.snapshot.pools[0].groups[0].last_error) <= 256
    finally:
        state.close()
        state.unlink()
```

- [ ] **Step 2: Run the shared-memory tests and verify RED**

Run: `uv run pytest tests/ygo/test_shared.py -q`

Expected: import fails because `SharedState` does not exist.

- [ ] **Step 3: Implement the double-buffer protocol**

Use a fixed header containing:

```python
MAGIC = b"YGO1"
SCHEMA_VERSION = 1
HEADER = struct.Struct("<4sHBBQIIQ")
```

`SharedState.write()` must:

1. serialize the snapshot;
2. truncate each `last_error` to 256 characters and set
   `telemetry_overflow=True` if the first payload does not fit;
3. publish an odd generation header;
4. write the inactive slot;
5. publish an even generation with payload length and CRC32.

`read()` must read the header twice and return `None` for odd generations,
header changes, invalid bounds, bad magic/schema, checksum mismatch, or invalid
JSON. It must never expose a partial snapshot.

- [ ] **Step 4: Verify GREEN and resource cleanup**

Run: `uv run pytest tests/ygo/test_shared.py -q`

Expected: all protocol tests pass without resource-tracker warnings.

- [ ] **Step 5: Commit the protocol**

```bash
git add src/ygo/telemetry/shared.py tests/ygo/test_shared.py
git commit -m "feat(ygo): add shared memory telemetry protocol"
```

### Task 3: Runtime Registry and Discovery

**Files:**
- Create: `src/ygo/telemetry/registry.py`
- Create: `src/ygo/monitor.py`
- Test: `tests/ygo/test_registry.py`
- Test: `tests/ygo/test_monitor.py`

- [ ] **Step 1: Write failing registry tests**

```python
def test_registry_round_trip(tmp_path):
    registry = RuntimeRegistry(tmp_path)
    entry = RegistryEntry(
        pid=os.getpid(),
        process_started_at=psutil.Process().create_time(),
        shared_memory_name="ygo-test",
        capacity=4096,
        command="pytest",
        cwd=str(tmp_path),
    )
    registry.register(entry)
    assert registry.entries() == [entry]
    registry.unregister(entry.pid, entry.process_started_at)
    assert registry.entries() == []


def test_discovery_removes_reused_pid(tmp_path):
    registry = RuntimeRegistry(tmp_path, process_identity=lambda pid: 999.0)
    registry.register(make_entry(pid=42, process_started_at=100.0))
    assert registry.live_entries(clean_stale=True) == []
    assert registry.entries() == []
```

- [ ] **Step 2: Run registry tests and verify RED**

Run: `uv run pytest tests/ygo/test_registry.py tests/ygo/test_monitor.py -q`

Expected: imports fail because registry and monitor modules do not exist.

- [ ] **Step 3: Implement private atomic registry files**

`RuntimeRegistry` must default to `platformdirs.user_runtime_path("ygo")`, set
Unix directory permissions to `0700`, write `<pid>-<start_ns>.json` via a
temporary file and `Path.replace()`, and set Unix file permissions to `0600`.
Malformed entries are ignored. Process identity uses
`psutil.Process(pid).create_time()` and treats `NoSuchProcess` and
`ZombieProcess` as dead.

- [ ] **Step 4: Implement live snapshot discovery**

`read_live_snapshots(registry)` must open each compatible segment, read one
snapshot, close the reader without unlinking it, and return records containing
the registry entry, generation, snapshot, and heartbeat age. One broken or
incompatible producer must not prevent reading the others.

- [ ] **Step 5: Verify GREEN and commit**

Run: `uv run pytest tests/ygo/test_registry.py tests/ygo/test_monitor.py -q`

Expected: registry and discovery tests pass.

```bash
git add src/ygo/telemetry/registry.py src/ygo/monitor.py tests/ygo/test_registry.py tests/ygo/test_monitor.py
git commit -m "feat(ygo): discover local telemetry producers"
```

### Task 4: Coalescing Process Publisher

**Files:**
- Create: `src/ygo/telemetry/publisher.py`
- Test: `tests/ygo/test_publisher.py`

- [ ] **Step 1: Write failing publisher tests**

```python
def test_publisher_coalesces_updates(fake_transport, clock):
    publisher = TelemetryPublisher(transport=fake_transport, clock=clock, start_thread=False)
    publisher.register_pool("p1", backend="threading", n_jobs=4, groups={"quote": 10})
    publisher.record_completion("p1", "quote", failed=False)
    publisher.record_completion("p1", "quote", failed=True, error="timeout")
    assert fake_transport.write_count == 1
    clock.advance(0.1)
    publisher.tick()
    assert fake_transport.write_count == 2
    assert fake_transport.last.pools[0].groups[0].completed == 2
    assert fake_transport.last.pools[0].groups[0].failed == 1


def test_publisher_swallows_transport_failure(failing_transport):
    publisher = TelemetryPublisher(
        transport=failing_transport,
        start_thread=False,
        warn=lambda message: None,
    )
    publisher.register_pool("p1", backend="threading", n_jobs=1, groups={"g": 1})
    publisher.record_completion("p1", "g", failed=False)
```

- [ ] **Step 2: Run publisher tests and verify RED**

Run: `uv run pytest tests/ygo/test_publisher.py -q`

Expected: import fails because `TelemetryPublisher` does not exist.

- [ ] **Step 3: Implement publisher state and heartbeat**

The publisher must be single-writer and lock-protected. It owns mutable internal
pool/group counters but publishes immutable snapshots. State changes mark it
dirty; writes occur at most every 100 ms, while a daemon tick publishes a
heartbeat at least once per second. Pool completion forces one final write.

Expose a process singleton:

```python
def get_publisher(*, enabled: bool = True) -> PublisherProtocol:
    ...


class NullPublisher:
    def register_pool(...): ...
    def record_completion(...): ...
    def complete_pool(...): ...
```

Every public publisher method catches telemetry errors, disables the broken
transport after the first failure, and emits at most one warning.

- [ ] **Step 4: Verify GREEN and commit**

Run: `uv run pytest tests/ygo/test_publisher.py -q`

Expected: coalescing, heartbeat, counters, failure isolation, and close tests
pass.

```bash
git add src/ygo/telemetry/publisher.py tests/ygo/test_publisher.py
git commit -m "feat(ygo): publish aggregate task telemetry"
```

### Task 5: Integrate Pool and Compact Inline Progress

**Files:**
- Modify: `src/ygo/_pool.py`
- Modify: `src/ygo/progress.py`
- Test: `tests/ygo/test_pool_monitoring.py`
- Test: `tests/ygo/test_progress.py`

- [ ] **Step 1: Write failing Pool integration tests**

```python
def test_pool_publishes_group_progress(fake_publisher):
    pool = Pool(
        n_jobs=1,
        show_progress=False,
        monitor=True,
        _publisher=fake_publisher,
    )
    pool.submit(lambda value: value, job_name="quote")(value=1)
    pool.submit(lambda value: value, job_name="quote")(value=2)
    assert pool.do() == [1, 2]
    assert fake_publisher.registered_groups == {"quote": 2}
    assert fake_publisher.completions == [("quote", False), ("quote", False)]
    assert fake_publisher.completed is True


def test_show_progress_false_does_not_disable_monitor(fake_publisher):
    pool = Pool(show_progress=False, monitor=True, _publisher=fake_publisher)
    pool.submit(lambda: 1, job_name="g")()
    pool.do()
    assert fake_publisher.registered is True
```

Add a progress test asserting that two groups create one Rich progress task
whose total is the sum of both groups.

- [ ] **Step 2: Run Pool tests and verify RED**

Run:

```bash
uv run pytest tests/ygo/test_pool_monitoring.py tests/ygo/test_progress.py -q
```

Expected: `Pool` rejects `monitor` and `_publisher`.

- [ ] **Step 3: Add Pool telemetry hooks**

Add `monitor: bool = True` and a private injectable publisher to `Pool`.
Generate a stable pool ID once per instance. Before execution, register group
totals. Extend the internal `run_job` result with an error summary and invoke a
completion callback as unordered joblib results arrive. Always mark the pool
done in `finally`, without changing the public result shape.

Respect `YGO_MONITOR=0`; `show_progress=False` must affect only inline output.

- [ ] **Step 4: Replace multi-row inline display**

In the progress branch of `multi_task_name`, create exactly one task named
`ygo` with `total=sum(len(jobs) for jobs in job_map.values())`. Update that same
task for every completion and mark it failed when any job fails. Ensure
`ProgressManager.__exit__()` clears all task maps and failure state so a reused
manager cannot inherit prior colors.

- [ ] **Step 5: Verify GREEN and commit**

Run:

```bash
uv run pytest tests/ygo/test_pool_monitoring.py tests/ygo/test_progress.py -q
uv run pytest tests/ -q
```

Expected: focused tests pass and the existing suite remains green.

```bash
git add src/ygo/_pool.py src/ygo/progress.py tests/ygo/test_pool_monitoring.py tests/ygo/test_progress.py
git commit -m "feat(ygo): report pool progress to telemetry"
```

### Task 6: Incremental Textual Dashboard and CLI

**Files:**
- Create: `src/ygo/tui.py`
- Create: `src/ygo/cli.py`
- Test: `tests/ygo/test_tui.py`
- Test: `tests/ygo/test_cli.py`

- [ ] **Step 1: Write failing row-diff and CLI tests**

```python
def test_reconcile_updates_only_changed_cell(fake_table, rows):
    reconciler = TableReconciler(fake_table)
    reconciler.apply(rows.initial)
    fake_table.calls.clear()
    reconciler.apply(rows.with_completed_incremented)
    assert fake_table.calls == [
        ("update_cell", rows.row_key, "progress", "5/10"),
    ]


def test_reconcile_does_nothing_for_same_generation(fake_table, rows):
    reconciler = TableReconciler(fake_table)
    reconciler.apply(rows.initial, generation=2)
    fake_table.calls.clear()
    reconciler.apply(rows.initial, generation=2)
    assert fake_table.calls == []


def test_ps_prints_live_groups(monkeypatch, capsys, live_process):
    monkeypatch.setattr("ygo.cli.read_live_snapshots", lambda: [live_process])
    assert main(["ps"]) == 0
    assert "quote" in capsys.readouterr().out
```

- [ ] **Step 2: Run UI tests and verify RED**

Run: `uv run pytest tests/ygo/test_tui.py tests/ygo/test_cli.py -q`

Expected: imports fail because TUI and CLI modules do not exist.

- [ ] **Step 3: Implement stable row reconciliation**

`TableReconciler` must key rows by `pid:pool_id:group_id`, cache the last
rendered cell dictionary, skip unchanged generations, use `add_row()` and
`remove_row()` for structural changes, and call `update_cell()` only when a
cached value changes. It must not clear or reconstruct the `DataTable`.

`YgoTopApp` mounts one `DataTable`, polls every 0.2 seconds, updates derived
elapsed/rate cells at most every 0.5 seconds, and binds `q`, `r`, `e`, and `l`.
It uses Textual's alternate screen and keeps stable ordering unless a row
changes active/problem/recent section.

- [ ] **Step 4: Implement CLI commands**

Use `argparse` with `main(argv: list[str] | None = None) -> int`.

- `top` runs `YgoTopApp`.
- `ps` prints one current Rich table.
- `show <pool-id>` prints process, backend, group counters, and heartbeat age.
- `errors <pool-id>` prints non-empty group error summaries.
- `run -- <command>` executes the command with inherited environment and
  `YGO_MONITOR=1` unless explicitly set.

Missing pool IDs return exit code 1; an empty live registry is a successful
empty `ps` and a valid empty dashboard.

- [ ] **Step 5: Run a real Textual pilot test**

Add an async test using `async with app.run_test()` that feeds two generations
and verifies the same `DataTable` instance remains mounted while its progress
cell changes.

Run: `uv run pytest tests/ygo/test_tui.py tests/ygo/test_cli.py -q`

Expected: reconciliation, pilot, and CLI tests pass.

- [ ] **Step 6: Commit CLI and TUI**

```bash
git add src/ygo/tui.py src/ygo/cli.py tests/ygo/test_tui.py tests/ygo/test_cli.py
git commit -m "feat(ygo): add incremental top dashboard"
```

### Task 7: Documentation and End-to-End Verification

**Files:**
- Modify: `README.md`
- Test: `tests/ygo/test_end_to_end.py`

- [ ] **Step 1: Write a failing producer/reader integration test**

Launch a Python subprocess that creates a monitored `Pool`, blocks on a
temporary sentinel, and prints its pool ID. From the test process, discover the
registry entry and assert the group is visible. Release the sentinel, wait for
completion, and assert the group becomes `done`. Always terminate the producer
and clean its runtime files in `finally`.

- [ ] **Step 2: Run the integration test and verify RED**

Run: `uv run pytest tests/ygo/test_end_to_end.py -q`

Expected: the first run fails on the missing or incomplete cross-process
lifecycle behavior.

- [ ] **Step 3: Complete lifecycle cleanup**

Fix only the lifecycle gaps demonstrated by the failing test: normal shutdown
must unregister and unlink, readers must never unlink producer memory, and
abnormal producer termination must be recognized as stale without crashing
discovery.

- [ ] **Step 4: Update README**

Document:

```bash
ygo top
ygo ps
ygo show <pool-id>
ygo errors <pool-id>
ygo run -- python script.py
```

Explain that `show_progress=True` remains the default, now uses one compact
inline row, and is independent from `monitor=False`/`YGO_MONITOR=0`.

- [ ] **Step 5: Run complete verification**

Run:

```bash
uv run pytest tests/ -q
uv run ruff format .
uv run ruff format --check .
uv run ruff check .
uv build
uv run ygo ps
```

Expected: all tests pass, Ruff reports no errors, wheel and sdist build, and
`ygo ps` exits zero with either live rows or an empty table.

- [ ] **Step 6: Inspect package and commit**

Verify the built wheel contains `ygo/telemetry`, `ygo/cli.py`, `ygo/tui.py`,
and the `ygo` console entry point.

```bash
git add README.md tests/ygo/test_end_to_end.py
git commit -m "docs(ygo): document task monitor"
```
