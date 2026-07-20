import os

import psutil

from ygo.telemetry.registry import RegistryEntry, RuntimeRegistry


def make_entry(
    *,
    pid: int = 42,
    process_started_at: float = 100.0,
    shared_memory_name: str = "ygo-test",
) -> RegistryEntry:
    return RegistryEntry(
        pid=pid,
        process_started_at=process_started_at,
        shared_memory_name=shared_memory_name,
        capacity=4096,
        command="pytest",
        cwd="/tmp",
    )


def test_registry_round_trip(tmp_path):
    registry = RuntimeRegistry(tmp_path)
    entry = make_entry(
        pid=os.getpid(),
        process_started_at=psutil.Process().create_time(),
    )

    registry.register(entry)

    assert registry.entries() == [entry]
    registry.unregister(entry.pid, entry.process_started_at)
    assert registry.entries() == []


def test_discovery_removes_reused_pid(tmp_path):
    registry = RuntimeRegistry(tmp_path, process_identity=lambda pid: 999.0)
    registry.register(make_entry())

    assert registry.live_entries(clean_stale=True) == []
    assert registry.entries() == []


def test_registry_ignores_malformed_entry(tmp_path):
    registry = RuntimeRegistry(tmp_path)
    (tmp_path / "bad.json").write_text("{", encoding="utf-8")

    assert registry.entries() == []
