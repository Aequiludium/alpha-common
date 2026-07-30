import os
import time

import psutil

from ygo.monitor import read_live_snapshots, read_monitor_state
from ygo.telemetry.history import HistoryRecord, HistoryStore, make_task_key
from ygo.telemetry.model import GroupSnapshot, PoolSnapshot, ProcessSnapshot
from ygo.telemetry.registry import RegistryEntry, RuntimeRegistry
from ygo.telemetry.shared import SharedState


def make_snapshot() -> ProcessSnapshot:
    return ProcessSnapshot(
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
                    ),
                ),
            ),
        ),
    )


def test_monitor_reads_live_snapshot(tmp_path):
    state = SharedState.create(capacity=4096)
    registry = RuntimeRegistry(tmp_path)
    started_at = psutil.Process().create_time()
    entry = RegistryEntry(
        pid=os.getpid(),
        process_started_at=started_at,
        shared_memory_name=state.name,
        capacity=state.capacity,
        command="pytest",
        cwd=str(tmp_path),
    )
    try:
        state.write(make_snapshot(), heartbeat_ns=time.monotonic_ns())
        registry.register(entry)

        records = read_live_snapshots(registry)

        assert len(records) == 1
        assert records[0].entry == entry
        assert records[0].snapshot.pid == 123
        assert records[0].generation == 2
        assert records[0].heartbeat_age >= 0
    finally:
        state.close()
        state.unlink()


def test_monitor_skips_missing_segment(tmp_path):
    registry = RuntimeRegistry(tmp_path)
    registry.register(
        RegistryEntry(
            pid=os.getpid(),
            process_started_at=psutil.Process().create_time(),
            shared_memory_name="does-not-exist",
            capacity=4096,
            command="pytest",
            cwd=str(tmp_path),
        )
    )

    assert read_live_snapshots(registry) == []


def test_monitor_merges_history_and_prefers_live_task(tmp_path):
    runtime_dir = tmp_path / "runtime"
    history = HistoryStore(tmp_path / "history")
    registry = RuntimeRegistry(runtime_dir)
    state = SharedState.create(capacity=4096)
    process_started_at = psutil.Process().create_time()
    entry = RegistryEntry(
        pid=os.getpid(),
        process_started_at=process_started_at,
        shared_memory_name=state.name,
        capacity=state.capacity,
        command="pytest",
        cwd=str(tmp_path),
    )
    live_key = make_task_key(
        os.getpid(),
        process_started_at,
        "pool-1",
        "quote",
        process_started_at,
    )
    duplicate = HistoryRecord(
        task_key=live_key,
        pid=os.getpid(),
        process_started_at=process_started_at,
        pool_id="pool-1",
        group_id="quote",
        command="old command",
        status="done",
        total=10,
        completed=10,
        failed=0,
        last_error=None,
        log_path=None,
        registered_at=process_started_at,
        started_at=901.0,
        finished_at=906.0,
        elapsed_seconds=5.0,
        rate=2.0,
    )
    historical = HistoryRecord(
        task_key=make_task_key(99, 2.0, "pool-2", "history", 800.0),
        pid=99,
        process_started_at=2.0,
        pool_id="pool-2",
        group_id="history",
        command="python old.py",
        status="done",
        total=1,
        completed=1,
        failed=0,
        last_error=None,
        log_path=None,
        registered_at=800.0,
        started_at=801.0,
        finished_at=802.0,
        elapsed_seconds=1.0,
        rate=1.0,
    )
    live_snapshot = make_snapshot()
    live_snapshot = ProcessSnapshot(
        pid=os.getpid(),
        process_started_at=process_started_at,
        command="pytest",
        cwd=str(tmp_path),
        pools=live_snapshot.pools,
    )
    try:
        history.append(duplicate)
        history.append(historical)
        state.write(live_snapshot, heartbeat_ns=time.monotonic_ns())
        registry.register(entry)

        monitored = read_monitor_state(registry, history)

        tasks = {task.key: task for task in monitored.tasks}
        assert set(tasks) == {live_key, historical.task_key}
        assert tasks[live_key].status == "running"
        assert tasks[live_key].command == "pytest"
        assert tasks[historical.task_key].elapsed_seconds == 1.0
    finally:
        state.close()
        state.unlink()


def test_monitor_uses_process_start_as_old_snapshot_registration_fallback(tmp_path):
    state = SharedState.create(capacity=4096)
    registry = RuntimeRegistry(tmp_path / "runtime")
    history = HistoryStore(tmp_path / "history")
    process_started_at = psutil.Process().create_time()
    entry = RegistryEntry(
        pid=os.getpid(),
        process_started_at=process_started_at,
        shared_memory_name=state.name,
        capacity=state.capacity,
        command="pytest",
        cwd=str(tmp_path),
    )
    snapshot = ProcessSnapshot(
        pid=os.getpid(),
        process_started_at=process_started_at,
        command="pytest",
        cwd=str(tmp_path),
        pools=make_snapshot().pools,
    )
    try:
        state.write(snapshot, heartbeat_ns=time.monotonic_ns())
        registry.register(entry)

        task = read_monitor_state(registry, history).tasks[0]

        assert task.registered_at == process_started_at
        assert task.started_at is None
    finally:
        state.close()
        state.unlink()
