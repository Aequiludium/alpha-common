from __future__ import annotations

import hashlib
import json
import os
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path

from platformdirs import user_state_path

HISTORY_LIMIT = 100
HISTORY_SCHEMA_VERSION = 1


@dataclass(frozen=True, slots=True)
class HistoryRecord:
    task_key: str
    pid: int
    process_started_at: float
    pool_id: str
    group_id: str
    command: str
    status: str
    total: int
    completed: int
    failed: int
    last_error: str | None
    log_path: str | None
    registered_at: float
    started_at: float
    finished_at: float
    elapsed_seconds: float
    rate: float
    schema_version: int = HISTORY_SCHEMA_VERSION

    def to_json(self) -> str:
        return json.dumps(
            asdict(self),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )

    @classmethod
    def from_json(cls, value: str) -> HistoryRecord:
        try:
            payload = json.loads(value)
            if not isinstance(payload, dict):
                raise ValueError("history record must be an object")
            if payload.get("schema_version") != HISTORY_SCHEMA_VERSION:
                raise ValueError("unsupported history schema")
            last_error = payload.get("last_error")
            log_path = payload.get("log_path")
            return cls(
                task_key=str(payload["task_key"]),
                pid=int(payload["pid"]),
                process_started_at=float(payload["process_started_at"]),
                pool_id=str(payload["pool_id"]),
                group_id=str(payload["group_id"]),
                command=str(payload["command"]),
                status=str(payload["status"]),
                total=int(payload["total"]),
                completed=int(payload["completed"]),
                failed=int(payload["failed"]),
                last_error=None if last_error is None else str(last_error),
                log_path=None if log_path is None else str(log_path),
                registered_at=float(payload["registered_at"]),
                started_at=float(payload["started_at"]),
                finished_at=float(payload["finished_at"]),
                elapsed_seconds=float(payload["elapsed_seconds"]),
                rate=float(payload["rate"]),
                schema_version=HISTORY_SCHEMA_VERSION,
            )
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            raise ValueError("invalid ygo history record") from exc


def make_task_key(
    pid: int,
    process_started_at: float,
    pool_id: str,
    group_id: str,
) -> str:
    identity_ns = int(process_started_at * 1_000_000_000)
    return f"{pid}:{identity_ns}:{pool_id}:{group_id}"


class HistoryStore:
    def __init__(self, root: str | Path | None = None):
        if root is None:
            configured = os.environ.get("YGO_HISTORY_DIR")
            root = Path(configured) if configured else user_state_path("ygo") / "history"
        self.root = Path(root)

    def append(self, record: HistoryRecord) -> None:
        self._ensure_root()
        target = self._record_path(record.task_key)
        temporary = self.root / f".{target.stem}.{uuid.uuid4().hex}.tmp"
        temporary.write_text(record.to_json(), encoding="utf-8")
        _chmod(temporary, 0o600)
        temporary.replace(target)
        self._prune(HISTORY_LIMIT)

    def recent(self, limit: int = HISTORY_LIMIT) -> list[HistoryRecord]:
        if limit < 0:
            raise ValueError("history limit must be non-negative")
        records = self._read_valid()
        records.sort(
            key=lambda item: (item.finished_at, item.task_key),
            reverse=True,
        )
        self._remove_records(records[limit:])
        return records[:limit]

    def _prune(self, limit: int) -> None:
        self.recent(limit)

    def _read_valid(self) -> list[HistoryRecord]:
        if not self.root.exists():
            return []
        records: list[HistoryRecord] = []
        for path in self.root.glob("*.json"):
            try:
                records.append(HistoryRecord.from_json(path.read_text(encoding="utf-8")))
            except (OSError, ValueError):
                continue
        return records

    def _remove_records(self, records: list[HistoryRecord]) -> None:
        for record in records:
            self._record_path(record.task_key).unlink(missing_ok=True)

    def _record_path(self, task_key: str) -> Path:
        digest = hashlib.sha256(task_key.encode("utf-8")).hexdigest()
        return self.root / f"{digest}.json"

    def _ensure_root(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        _chmod(self.root, 0o700)


def _chmod(path: Path, mode: int) -> None:
    if os.name != "nt":
        path.chmod(mode)
