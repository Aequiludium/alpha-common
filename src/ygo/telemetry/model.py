from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Any

SCHEMA_VERSION = 1


@dataclass(frozen=True, slots=True)
class GroupSnapshot:
    id: str
    status: str
    total: int
    completed: int
    failed: int
    started_monotonic: float
    last_error: str | None = None


@dataclass(frozen=True, slots=True)
class PoolSnapshot:
    id: str
    backend: str
    n_jobs: int
    status: str
    groups: tuple[GroupSnapshot, ...] = ()


@dataclass(frozen=True, slots=True)
class ProcessSnapshot:
    pid: int
    process_started_at: float
    command: str
    cwd: str
    pools: tuple[PoolSnapshot, ...] = ()
    telemetry_overflow: bool = False
    schema_version: int = SCHEMA_VERSION

    def to_json(self) -> str:
        return json.dumps(
            asdict(self),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )

    @classmethod
    def from_json(cls, value: str | bytes) -> ProcessSnapshot:
        try:
            payload = json.loads(value)
        except (json.JSONDecodeError, TypeError, UnicodeDecodeError) as exc:
            raise ValueError("invalid telemetry snapshot JSON") from exc

        if not isinstance(payload, dict):
            raise ValueError("invalid telemetry snapshot payload")
        if payload.get("schema_version") != SCHEMA_VERSION:
            raise ValueError(f"unsupported telemetry schema: {payload.get('schema_version')!r}")

        try:
            pools = tuple(_pool_from_dict(item) for item in payload["pools"])
            return cls(
                pid=int(payload["pid"]),
                process_started_at=float(payload["process_started_at"]),
                command=str(payload["command"]),
                cwd=str(payload["cwd"]),
                pools=pools,
                telemetry_overflow=bool(payload.get("telemetry_overflow", False)),
                schema_version=SCHEMA_VERSION,
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("invalid telemetry snapshot payload") from exc


def _pool_from_dict(payload: Any) -> PoolSnapshot:
    if not isinstance(payload, dict):
        raise ValueError("pool snapshot must be an object")
    groups = tuple(_group_from_dict(item) for item in payload["groups"])
    return PoolSnapshot(
        id=str(payload["id"]),
        backend=str(payload["backend"]),
        n_jobs=int(payload["n_jobs"]),
        status=str(payload["status"]),
        groups=groups,
    )


def _group_from_dict(payload: Any) -> GroupSnapshot:
    if not isinstance(payload, dict):
        raise ValueError("group snapshot must be an object")
    last_error = payload.get("last_error")
    return GroupSnapshot(
        id=str(payload["id"]),
        status=str(payload["status"]),
        total=int(payload["total"]),
        completed=int(payload["completed"]),
        failed=int(payload["failed"]),
        started_monotonic=float(payload["started_monotonic"]),
        last_error=None if last_error is None else str(last_error),
    )
