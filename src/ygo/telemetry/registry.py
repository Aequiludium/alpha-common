from __future__ import annotations

import json
import os
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable

import psutil
from platformdirs import user_runtime_path


@dataclass(frozen=True, slots=True)
class RegistryEntry:
    pid: int
    process_started_at: float
    shared_memory_name: str
    capacity: int
    command: str
    cwd: str
    schema_version: int = 1
    package_version: str | None = None
    log_path: str | None = None

    def to_json(self) -> str:
        return json.dumps(
            asdict(self),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )

    @classmethod
    def from_json(cls, value: str) -> RegistryEntry:
        try:
            payload = json.loads(value)
            return cls(
                pid=int(payload["pid"]),
                process_started_at=float(payload["process_started_at"]),
                shared_memory_name=str(payload["shared_memory_name"]),
                capacity=int(payload["capacity"]),
                command=str(payload["command"]),
                cwd=str(payload["cwd"]),
                schema_version=int(payload.get("schema_version", 1)),
                package_version=_optional_string(payload.get("package_version")),
                log_path=_optional_string(payload.get("log_path")),
            )
        except (json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            raise ValueError("invalid ygo registry entry") from exc


class RuntimeRegistry:
    def __init__(
        self,
        root: str | Path | None = None,
        *,
        process_identity: Callable[[int], float | None] | None = None,
    ):
        self.root = Path(root) if root is not None else user_runtime_path("ygo")
        self._process_identity = process_identity or _process_identity

    def register(self, entry: RegistryEntry) -> Path:
        self._ensure_root()
        path = self._entry_path(entry.pid, entry.process_started_at)
        temporary = self.root / f".{path.name}.{uuid.uuid4().hex}.tmp"
        temporary.write_text(entry.to_json(), encoding="utf-8")
        _chmod(temporary, 0o600)
        temporary.replace(path)
        return path

    def unregister(self, pid: int, process_started_at: float) -> None:
        for path in self.root.glob(f"{pid}-*.json") if self.root.exists() else ():
            try:
                entry = RegistryEntry.from_json(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if entry.process_started_at == process_started_at:
                path.unlink(missing_ok=True)

    def entries(self) -> list[RegistryEntry]:
        if not self.root.exists():
            return []
        entries: list[RegistryEntry] = []
        for path in sorted(self.root.glob("*.json")):
            try:
                entries.append(RegistryEntry.from_json(path.read_text(encoding="utf-8")))
            except (OSError, ValueError):
                continue
        return entries

    def live_entries(self, *, clean_stale: bool = False) -> list[RegistryEntry]:
        live: list[RegistryEntry] = []
        for entry in self.entries():
            identity = self._process_identity(entry.pid)
            if identity is not None and abs(identity - entry.process_started_at) < 1e-6:
                live.append(entry)
            elif clean_stale:
                self.unregister(entry.pid, entry.process_started_at)
        return live

    def _entry_path(self, pid: int, process_started_at: float) -> Path:
        return self.root / f"{pid}-{int(process_started_at * 1_000_000_000)}.json"

    def _ensure_root(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        _chmod(self.root, 0o700)


def _process_identity(pid: int) -> float | None:
    try:
        return psutil.Process(pid).create_time()
    except (psutil.NoSuchProcess, psutil.ZombieProcess, psutil.AccessDenied):
        return None


def _optional_string(value: object) -> str | None:
    return None if value is None else str(value)


def _chmod(path: Path, mode: int) -> None:
    if os.name != "nt":
        path.chmod(mode)
