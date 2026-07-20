from __future__ import annotations

import time
from dataclasses import dataclass

from .telemetry.model import ProcessSnapshot
from .telemetry.registry import RegistryEntry, RuntimeRegistry
from .telemetry.shared import SharedState


@dataclass(frozen=True, slots=True)
class LiveProcess:
    entry: RegistryEntry
    generation: int
    heartbeat_age: float
    snapshot: ProcessSnapshot


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
