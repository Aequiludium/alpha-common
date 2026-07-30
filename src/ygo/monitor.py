from __future__ import annotations

import time
from dataclasses import dataclass

from .telemetry.history import HistoryRecord, HistoryStore, make_task_key
from .telemetry.model import ProcessSnapshot
from .telemetry.registry import RegistryEntry, RuntimeRegistry
from .telemetry.shared import SharedState


@dataclass(frozen=True, slots=True)
class LiveProcess:
    entry: RegistryEntry
    generation: int
    heartbeat_age: float
    snapshot: ProcessSnapshot


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


def read_live_snapshots(
    registry: RuntimeRegistry | None = None,
    *,
    now_ns: int | None = None,
) -> list[LiveProcess]:
    active_registry = registry or RuntimeRegistry()
    current_ns = time.monotonic_ns() if now_ns is None else now_ns
    records: list[LiveProcess] = []
    for entry in active_registry.live_entries(clean_stale=True):
        if entry.schema_version != 1:
            continue
        try:
            state = SharedState.open(entry.shared_memory_name)
        except (FileNotFoundError, OSError, ValueError):
            continue
        try:
            shared = state.read()
        finally:
            state.close()
        if shared is None:
            continue
        records.append(
            LiveProcess(
                entry=entry,
                generation=shared.generation,
                heartbeat_age=max(0.0, (current_ns - shared.heartbeat_ns) / 1_000_000_000),
                snapshot=shared.snapshot,
            )
        )
    return records


def read_monitor_state(
    registry: RuntimeRegistry | None = None,
    history: HistoryStore | None = None,
    *,
    now_ns: int | None = None,
) -> MonitorState:
    live_processes = read_live_snapshots(registry, now_ns=now_ns)
    active_history = history if history is not None else HistoryStore()
    history_records = active_history.recent()
    tasks = {record.task_key: _historical_task(record) for record in history_records}
    for process in live_processes:
        for task in _live_tasks(process):
            tasks[task.key] = task
    generation = (
        tuple(sorted((item.snapshot.pid, item.generation) for item in live_processes)),
        tuple((item.task_key, item.finished_at) for item in history_records),
    )
    return MonitorState(tuple(tasks.values()), generation)


def _live_tasks(process: LiveProcess) -> tuple[MonitoredTask, ...]:
    tasks: list[MonitoredTask] = []
    for pool in process.snapshot.pools:
        for group in pool.groups:
            registered_at = (
                group.registered_at
                if group.registered_at is not None
                else process.snapshot.process_started_at
            )
            tasks.append(
                MonitoredTask(
                    key=make_task_key(
                        process.snapshot.pid,
                        process.snapshot.process_started_at,
                        pool.id,
                        group.id,
                        registered_at,
                    ),
                    pid=process.snapshot.pid,
                    status=group.status,
                    completed=group.completed,
                    total=group.total,
                    failed=group.failed,
                    registered_at=registered_at,
                    started_at=group.started_at,
                    finished_at=group.finished_at,
                    started_monotonic=group.started_monotonic,
                    finished_monotonic=group.finished_monotonic,
                    elapsed_seconds=None,
                    rate=None,
                    group_id=group.id,
                    command=process.entry.command,
                    error=group.last_error,
                    log_path=process.entry.log_path,
                )
            )
    return tuple(tasks)


def _historical_task(record: HistoryRecord) -> MonitoredTask:
    return MonitoredTask(
        key=record.task_key,
        pid=record.pid,
        status=record.status,
        completed=record.completed,
        total=record.total,
        failed=record.failed,
        registered_at=record.registered_at,
        started_at=record.started_at,
        finished_at=record.finished_at,
        started_monotonic=None,
        finished_monotonic=None,
        elapsed_seconds=record.elapsed_seconds,
        rate=record.rate,
        group_id=record.group_id,
        command=record.command,
        error=record.last_error,
        log_path=record.log_path,
    )
