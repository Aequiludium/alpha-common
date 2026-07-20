import ctypes
import subprocess
import sys
from dataclasses import replace

from ygo.telemetry import shared as shared_module
from ygo.telemetry.model import GroupSnapshot, PoolSnapshot, ProcessSnapshot
from ygo.telemetry.shared import HEADER, SharedState


def make_snapshot(*, last_error: str | None = "timeout") -> ProcessSnapshot:
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
                        last_error=last_error,
                    ),
                ),
            ),
        ),
    )


def test_shared_state_round_trip():
    snapshot = make_snapshot()
    writer = SharedState.create(capacity=4096)
    reader = SharedState.open(writer.name)
    try:
        generation = writer.write(snapshot, heartbeat_ns=123456)
        read = reader.read()

        assert read is not None
        assert read.generation == generation
        assert read.heartbeat_ns == 123456
        assert read.snapshot == snapshot
    finally:
        reader.close()
        writer.close()
        writer.unlink()


def test_create_supports_structured_byte_memoryview(monkeypatch):
    class StructuredBufferSharedMemory:
        def __init__(self, *, create, size):
            assert create is True
            self.size = size
            self.name = "structured-buffer"
            self._name = self.name
            self.buf = memoryview((ctypes.c_ubyte * size)())

        def close(self):
            self.buf.release()

        def unlink(self):
            pass

    monkeypatch.setattr(
        shared_module.shared_memory,
        "SharedMemory",
        StructuredBufferSharedMemory,
    )

    state = SharedState.create(capacity=4096)
    try:
        assert HEADER.unpack_from(state._shm.buf)[0] == b"YGO1"
    finally:
        state.close()
        state.unlink()


def test_reader_rejects_checksum_mismatch():
    state = SharedState.create(capacity=4096)
    try:
        state.write(make_snapshot())
        state._shm.buf[state.active_payload_offset] ^= 1

        assert state.read() is None
    finally:
        state.close()
        state.unlink()


def test_reader_rejects_in_progress_generation():
    state = SharedState.create(capacity=4096)
    try:
        state.write(make_snapshot())
        magic, schema, active, flags, generation, length, checksum, heartbeat = HEADER.unpack_from(
            state._shm.buf
        )
        HEADER.pack_into(
            state._shm.buf,
            0,
            magic,
            schema,
            active,
            flags,
            generation + 1,
            length,
            checksum,
            heartbeat,
        )

        assert state.read() is None
    finally:
        state.close()
        state.unlink()


def test_overflow_truncates_error_details():
    oversized = make_snapshot(last_error="x" * 4000)
    state = SharedState.create(capacity=2048)
    try:
        state.write(oversized)
        read = state.read()

        assert read is not None
        assert read.snapshot.telemetry_overflow is True
        assert len(read.snapshot.pools[0].groups[0].last_error or "") == 256
        assert read.snapshot == replace(
            oversized,
            telemetry_overflow=True,
            pools=(
                replace(
                    oversized.pools[0],
                    groups=(
                        replace(
                            oversized.pools[0].groups[0],
                            last_error="x" * 256,
                        ),
                    ),
                ),
            ),
        )
    finally:
        state.close()
        state.unlink()


def test_reader_process_does_not_claim_ownership():
    state = SharedState.create(capacity=4096)
    try:
        state.write(make_snapshot())
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                (
                    "from ygo.telemetry.shared import SharedState; "
                    f"s = SharedState.open({state.name!r}); "
                    "assert s.read() is not None; s.close()"
                ),
            ],
            capture_output=True,
            text=True,
            check=False,
        )

        assert result.returncode == 0, result.stderr
        assert "resource_tracker" not in result.stderr
    finally:
        state.close()
        state.unlink()
