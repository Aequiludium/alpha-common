from __future__ import annotations

import struct
import time
import zlib
from dataclasses import dataclass, replace
from multiprocessing import shared_memory

from .model import SCHEMA_VERSION, GroupSnapshot, ProcessSnapshot

MAGIC = b"YGO1"
HEADER = struct.Struct("<4sHBBQIIQ")
DEFAULT_CAPACITY = 1024 * 1024
MIN_CAPACITY = HEADER.size + 512


class TelemetryOverflowError(ValueError):
    """Raised when even a reduced telemetry snapshot cannot fit."""


@dataclass(frozen=True, slots=True)
class SharedSnapshot:
    generation: int
    heartbeat_ns: int
    snapshot: ProcessSnapshot


class SharedState:
    def __init__(self, shm: shared_memory.SharedMemory, *, owner: bool):
        self._shm = shm
        self._owner = owner
        if shm.size < MIN_CAPACITY:
            raise ValueError(f"shared memory capacity must be at least {MIN_CAPACITY}")

    @classmethod
    def create(cls, *, capacity: int = DEFAULT_CAPACITY) -> SharedState:
        if capacity < MIN_CAPACITY:
            raise ValueError(f"shared memory capacity must be at least {MIN_CAPACITY}")
        shm = shared_memory.SharedMemory(create=True, size=capacity)
        state = cls(shm, owner=True)
        state._shm.buf[:] = b"\0" * capacity
        HEADER.pack_into(
            state._shm.buf,
            0,
            MAGIC,
            SCHEMA_VERSION,
            0,
            0,
            0,
            0,
            0,
            time.monotonic_ns(),
        )
        return state

    @classmethod
    def open(cls, name: str) -> SharedState:
        return cls(shared_memory.SharedMemory(name=name, create=False), owner=False)

    @property
    def name(self) -> str:
        return self._shm.name

    @property
    def capacity(self) -> int:
        return self._shm.size

    @property
    def slot_capacity(self) -> int:
        return (self.capacity - HEADER.size) // 2

    def _slot_offset(self, slot: int) -> int:
        return HEADER.size + slot * self.slot_capacity

    @property
    def active_payload_offset(self) -> int:
        header = self._unpack_header()
        return self._slot_offset(header[2])

    def write(
        self,
        snapshot: ProcessSnapshot,
        *,
        heartbeat_ns: int | None = None,
    ) -> int:
        payload = snapshot.to_json().encode("utf-8")
        if len(payload) > self.slot_capacity:
            snapshot = _truncate_snapshot(snapshot)
            payload = snapshot.to_json().encode("utf-8")
        if len(payload) > self.slot_capacity:
            raise TelemetryOverflowError(
                f"telemetry payload needs {len(payload)} bytes; "
                f"slot capacity is {self.slot_capacity}"
            )

        current = self._unpack_header()
        current_active = current[2] if current[0] == MAGIC else 0
        current_generation = current[4] if current[0] == MAGIC else 0
        if current_generation % 2:
            current_generation += 1
        pending_generation = current_generation + 1
        next_active = 1 - current_active
        heartbeat = heartbeat_ns if heartbeat_ns is not None else time.monotonic_ns()

        HEADER.pack_into(
            self._shm.buf,
            0,
            MAGIC,
            SCHEMA_VERSION,
            current_active,
            0,
            pending_generation,
            0,
            0,
            heartbeat,
        )
        offset = self._slot_offset(next_active)
        self._shm.buf[offset : offset + len(payload)] = payload

        completed_generation = pending_generation + 1
        HEADER.pack_into(
            self._shm.buf,
            0,
            MAGIC,
            SCHEMA_VERSION,
            next_active,
            0,
            completed_generation,
            len(payload),
            zlib.crc32(payload),
            heartbeat,
        )
        return completed_generation

    def read(self) -> SharedSnapshot | None:
        first = self._unpack_header()
        if not self._valid_header(first):
            return None
        _, _, active, _, generation, length, checksum, heartbeat = first
        offset = self._slot_offset(active)
        payload = bytes(self._shm.buf[offset : offset + length])
        second = self._unpack_header()
        if first != second or zlib.crc32(payload) != checksum:
            return None
        try:
            snapshot = ProcessSnapshot.from_json(payload)
        except ValueError:
            return None
        return SharedSnapshot(
            generation=generation,
            heartbeat_ns=heartbeat,
            snapshot=snapshot,
        )

    def _unpack_header(self) -> tuple[bytes, int, int, int, int, int, int, int]:
        return HEADER.unpack_from(self._shm.buf)

    def _valid_header(
        self,
        header: tuple[bytes, int, int, int, int, int, int, int],
    ) -> bool:
        magic, schema, active, _, generation, length, _, _ = header
        return (
            magic == MAGIC
            and schema == SCHEMA_VERSION
            and active in (0, 1)
            and generation > 0
            and generation % 2 == 0
            and 0 < length <= self.slot_capacity
        )

    def close(self) -> None:
        self._shm.close()

    def unlink(self) -> None:
        if not self._owner:
            return
        try:
            self._shm.unlink()
        except FileNotFoundError:
            pass


def _truncate_snapshot(snapshot: ProcessSnapshot) -> ProcessSnapshot:
    pools = tuple(
        replace(
            pool,
            groups=tuple(_truncate_group(group) for group in pool.groups),
        )
        for pool in snapshot.pools
    )
    return replace(snapshot, pools=pools, telemetry_overflow=True)


def _truncate_group(group: GroupSnapshot) -> GroupSnapshot:
    if group.last_error is None:
        return group
    return replace(group, last_error=group.last_error[:256])
