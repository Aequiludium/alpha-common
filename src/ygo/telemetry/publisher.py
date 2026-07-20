from __future__ import annotations

import atexit
import os
import shlex
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Protocol

import psutil
from loguru import logger

from .model import GroupSnapshot, PoolSnapshot, ProcessSnapshot
from .registry import RegistryEntry, RuntimeRegistry
from .shared import SharedState

PUBLISH_INTERVAL = 0.1
HEARTBEAT_INTERVAL = 1.0


class PublisherProtocol(Protocol):
    def register_pool(
        self,
        pool_id: str,
        *,
        backend: str,
        n_jobs: int,
        groups: dict[str, int],
    ) -> None: ...

    def record_completion(
        self,
        pool_id: str,
        group_id: str,
        *,
        failed: bool,
        error: str | None = None,
        started_monotonic: float,
        finished_monotonic: float,
    ) -> None: ...

    def complete_pool(self, pool_id: str) -> None: ...


@dataclass(slots=True)
class _GroupState:
    id: str
    total: int
    registered_monotonic: float
    status: str = "pending"
    started_monotonic: float | None = None
    finished_monotonic: float | None = None
    completed: int = 0
    failed: int = 0
    last_error: str | None = None


@dataclass(slots=True)
class _PoolState:
    id: str
    backend: str
    n_jobs: int
    status: str = "running"
    groups: dict[str, _GroupState] = field(default_factory=dict)


class TelemetryPublisher:
    def __init__(
        self,
        *,
        transport: SharedState | object | None = None,
        registry: RuntimeRegistry | None = None,
        clock: Callable[[], float] = time.monotonic,
        start_thread: bool = True,
        warn: Callable[[str], None] | None = None,
    ):
        self._clock = clock
        self._warn = warn or logger.warning
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._pools: dict[str, _PoolState] = {}
        self._dirty = False
        self._disabled = False
        self._warned = False
        self._closed = False
        self._last_write: float | None = None
        self._registry = registry
        self._entry: RegistryEntry | None = None
        self._transport = transport
        self._pid = os.getpid()
        self._process_started_at = psutil.Process(self._pid).create_time()

        if self._transport is None:
            self._transport = SharedState.create()
            self._registry = registry or RuntimeRegistry()
            self._entry = RegistryEntry(
                pid=self._pid,
                process_started_at=self._process_started_at,
                shared_memory_name=self._transport.name,
                capacity=self._transport.capacity,
                command=shlex.join(sys.argv),
                cwd=str(Path.cwd()),
            )
            self._registry.register(self._entry)

        if start_thread:
            self._thread = threading.Thread(
                target=self._run,
                name="ygo-telemetry",
                daemon=True,
            )
            self._thread.start()
        atexit.register(self.close)

    def register_pool(
        self,
        pool_id: str,
        *,
        backend: str,
        n_jobs: int,
        groups: dict[str, int],
    ) -> None:
        def action() -> None:
            now = self._clock()
            self._pools[pool_id] = _PoolState(
                id=pool_id,
                backend=backend,
                n_jobs=n_jobs,
                groups={
                    name: _GroupState(id=name, total=total, registered_monotonic=now)
                    for name, total in groups.items()
                },
            )
            self._dirty = True
            self._publish(force=True)

        self._safe(action)

    def record_completion(
        self,
        pool_id: str,
        group_id: str,
        *,
        failed: bool,
        error: str | None = None,
        started_monotonic: float,
        finished_monotonic: float,
    ) -> None:
        def action() -> None:
            group = self._pools[pool_id].groups[group_id]
            if group.started_monotonic is None or started_monotonic < group.started_monotonic:
                group.started_monotonic = started_monotonic
            if group.finished_monotonic is None or finished_monotonic > group.finished_monotonic:
                group.finished_monotonic = finished_monotonic
            group.status = "running"
            group.completed += 1
            if failed:
                group.failed += 1
                group.last_error = error
            if group.completed >= group.total:
                group.status = "error" if group.failed else "done"
            self._dirty = True
            self._publish(force=False)

        self._safe(action)

    def complete_pool(self, pool_id: str) -> None:
        def action() -> None:
            pool = self._pools[pool_id]
            pool.status = "error" if any(group.failed for group in pool.groups.values()) else "done"
            for group in pool.groups.values():
                if group.status in {"pending", "running"}:
                    group.status = "error" if group.failed else "done"
            self._dirty = True
            self._publish(force=True)

        self._safe(action)

    def tick(self) -> None:
        self._safe(lambda: self._publish(force=False, heartbeat=True))

    def _publish(self, *, force: bool, heartbeat: bool = False) -> None:
        now = self._clock()
        due = self._last_write is None or now - self._last_write >= PUBLISH_INTERVAL - 1e-9
        heartbeat_due = self._last_write is None or now - self._last_write >= HEARTBEAT_INTERVAL
        if not force and not (due and self._dirty) and not (heartbeat and heartbeat_due):
            return
        snapshot = self._snapshot()
        self._transport.write(snapshot, heartbeat_ns=int(now * 1_000_000_000))
        self._last_write = now
        self._dirty = False

    def _snapshot(self) -> ProcessSnapshot:
        return ProcessSnapshot(
            pid=self._pid,
            process_started_at=self._process_started_at,
            command=shlex.join(sys.argv),
            cwd=str(Path.cwd()),
            pools=tuple(
                PoolSnapshot(
                    id=pool.id,
                    backend=pool.backend,
                    n_jobs=pool.n_jobs,
                    status=pool.status,
                    groups=tuple(
                        GroupSnapshot(
                            id=group.id,
                            status=group.status,
                            total=group.total,
                            completed=group.completed,
                            failed=group.failed,
                            started_monotonic=(
                                group.started_monotonic
                                if group.started_monotonic is not None
                                else group.registered_monotonic
                            ),
                            last_error=group.last_error,
                            finished_monotonic=(
                                group.finished_monotonic
                                if group.status in {"done", "error"}
                                else None
                            ),
                        )
                        for group in pool.groups.values()
                    ),
                )
                for pool in self._pools.values()
            ),
        )

    def _safe(self, action: Callable[[], None]) -> None:
        with self._lock:
            if self._disabled or self._closed:
                return
            try:
                action()
            except Exception as exc:
                self._disabled = True
                if not self._warned:
                    self._warned = True
                    self._warn(f"ygo telemetry disabled: {exc}")

    def _run(self) -> None:
        while not self._stop.wait(PUBLISH_INTERVAL):
            self.tick()

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
        self._stop.set()
        if (
            self._thread is not None
            and self._thread.is_alive()
            and self._thread is not threading.current_thread()
        ):
            self._thread.join(timeout=1)
        if self._entry is not None and self._registry is not None:
            self._registry.unregister(self._entry.pid, self._entry.process_started_at)
        try:
            self._transport.close()
        finally:
            self._transport.unlink()


class NullPublisher:
    def register_pool(self, *args, **kwargs) -> None:
        pass

    def record_completion(self, *args, **kwargs) -> None:
        pass

    def complete_pool(self, *args, **kwargs) -> None:
        pass


_publisher: PublisherProtocol | None = None
_publisher_lock = threading.Lock()


def get_publisher(*, enabled: bool = True) -> PublisherProtocol:
    global _publisher
    if not enabled or os.getenv("YGO_MONITOR", "1").lower() in {"0", "false", "no", "off"}:
        return NullPublisher()
    with _publisher_lock:
        if _publisher is None:
            try:
                _publisher = TelemetryPublisher()
            except Exception as exc:
                logger.warning(f"ygo telemetry unavailable: {exc}")
                _publisher = NullPublisher()
        return _publisher
