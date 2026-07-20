from __future__ import annotations

import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

from textual.app import App, ComposeResult
from textual.widgets import DataTable, Footer, Header

from .monitor import LiveProcess, read_live_snapshots

COLUMNS = (
    ("pid", "PID"),
    ("status", "STATUS"),
    ("progress", "PROGRESS"),
    ("rate", "RATE"),
    ("failed", "FAIL"),
    ("elapsed", "ELAPSED"),
    ("group", "GROUP"),
    ("command", "COMMAND"),
)


@dataclass(frozen=True, slots=True)
class MonitorRow:
    key: str
    cells: dict[str, str]
    error: str | None = None
    log_path: str | None = None


def rows_from_processes(
    processes: Iterable[LiveProcess],
    *,
    now: float | None = None,
) -> list[MonitorRow]:
    current = time.monotonic() if now is None else now
    rows: list[MonitorRow] = []
    for process in processes:
        for pool in process.snapshot.pools:
            for group in pool.groups:
                elapsed = max(0.0, current - group.started_monotonic)
                rate = group.completed / elapsed if elapsed else 0.0
                rows.append(
                    MonitorRow(
                        key=f"{process.snapshot.pid}:{pool.id}:{group.id}",
                        cells={
                            "pid": str(process.snapshot.pid),
                            "status": group.status,
                            "progress": f"{group.completed}/{group.total}",
                            "rate": f"{rate:.1f}/s",
                            "failed": str(group.failed),
                            "elapsed": _format_duration(elapsed),
                            "group": group.id,
                            "command": process.entry.command,
                        },
                        error=group.last_error,
                        log_path=process.entry.log_path,
                    )
                )
    return rows


class TableReconciler:
    def __init__(self, table: Any):
        self.table = table
        self._cells: dict[str, dict[str, str]] = {}
        self._generation: object = None

    def apply(self, rows: Iterable[MonitorRow], *, generation: object) -> None:
        if generation == self._generation:
            return
        next_rows = {row.key: row for row in rows}

        for key in self._cells.keys() - next_rows.keys():
            self.table.remove_row(key)
            del self._cells[key]

        for key, row in next_rows.items():
            previous = self._cells.get(key)
            if previous is None:
                self.table.add_row(
                    *(row.cells[column] for column, _ in COLUMNS),
                    key=key,
                )
                self._cells[key] = dict(row.cells)
                continue
            for column, value in row.cells.items():
                if previous.get(column) != value:
                    self.table.update_cell(key, column, value)
                    previous[column] = value

        self._generation = generation


class YgoTopApp(App[None]):
    TITLE = "ygo top"
    BINDINGS = [
        ("q", "quit", "Quit"),
        ("r", "refresh", "Refresh"),
        ("e", "errors", "Errors"),
        ("l", "log_path", "Log"),
    ]
    CSS = """
    DataTable {
        height: 1fr;
    }
    """

    def __init__(
        self,
        *,
        provider: Callable[[], list[LiveProcess]] = read_live_snapshots,
    ):
        super().__init__()
        self._provider = provider
        self._reconciler: TableReconciler | None = None
        self._rows: dict[str, MonitorRow] = {}

    def compose(self) -> ComposeResult:
        yield Header()
        yield DataTable(id="tasks", cursor_type="row", zebra_stripes=True)
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one("#tasks", DataTable)
        for key, label in COLUMNS:
            table.add_column(label, key=key)
        self._reconciler = TableReconciler(table)
        self.refresh_monitor()
        self.set_interval(0.2, self.refresh_monitor)

    def refresh_monitor(self) -> None:
        if self._reconciler is None:
            return
        now = time.monotonic()
        processes = self._provider()
        rows = rows_from_processes(processes, now=now)
        self._rows = {row.key: row for row in rows}
        generation = (
            tuple(sorted((item.snapshot.pid, item.generation) for item in processes)),
            int(now * 2),
        )
        self._reconciler.apply(rows, generation=generation)
        self.sub_title = f"{len(rows)} groups · 0.2s"

    def action_refresh(self) -> None:
        if self._reconciler is not None:
            self._reconciler._generation = None
        self.refresh_monitor()

    def action_errors(self) -> None:
        row = self._selected_row()
        self.notify(row.error if row and row.error else "No error for selected row")

    def action_log_path(self) -> None:
        row = self._selected_row()
        self.notify(row.log_path if row and row.log_path else "No log path registered")

    def _selected_row(self) -> MonitorRow | None:
        table = self.query_one("#tasks", DataTable)
        if table.row_count == 0:
            return None
        row_key, _ = table.coordinate_to_cell_key(table.cursor_coordinate)
        return self._rows.get(str(row_key.value))


def _format_duration(seconds: float) -> str:
    total = int(seconds)
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"
