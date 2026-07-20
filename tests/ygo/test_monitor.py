import os
import time

import psutil

from ygo.monitor import read_live_snapshots
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
