from __future__ import annotations

import datetime
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Any

from rich.cells import cell_len
from rich.console import Console, ConsoleOptions, RenderResult
from rich.measure import Measurement
from textual.app import App, ComposeResult
from textual.widgets import DataTable, Footer, Header

from .monitor import MonitoredTask, MonitorState, read_monitor_state

COLUMNS = (
    ("pid", "PID"),
    ("status", "STATUS"),
    ("progress", "PROGRESS"),
    ("rate", "RATE"),
    ("failed", "FAIL"),
    ("elapsed", "ELAPSED"),
    ("started", "STARTED"),
    ("group", "GROUP"),
    ("command", "COMMAND"),
)

SortValue = int | float | str


@dataclass(frozen=True, slots=True)
class TableCell:
    text: str
    sort_value: SortValue

    def __rich_console__(
        self,
        console: Console,
        options: ConsoleOptions,
    ) -> RenderResult:
        yield self.text

    def __rich_measure__(
        self,
        console: Console,
        options: ConsoleOptions,
    ) -> Measurement:
        width = cell_len(self.text)
        return Measurement(width, width)

    def __str__(self) -> str:
        return self.text


@dataclass(frozen=True, slots=True)
class MonitorRow:
    key: str
    cells: dict[str, TableCell]
    error: str | None = None
    log_path: str | None = None


@dataclass(frozen=True, slots=True)
class ReconcileResult:
    structure_changed: bool
    changed_columns: frozenset[str]


def row_from_task(
    task: MonitoredTask,
    *,
    now: float | None = None,
) -> MonitorRow:
    current = time.monotonic() if now is None else now
    elapsed, rate = _task_metrics(task, current)
    started_text = (
        "--"
        if task.started_at is None
        else datetime.datetime.fromtimestamp(task.started_at).strftime("%Y-%m-%d %H:%M:%S")
    )
    progress = task.completed / task.total if task.total else 0.0
    order_time = task.started_at if task.started_at is not None else task.registered_at
    return MonitorRow(
        key=task.key,
        cells={
            "pid": TableCell(str(task.pid), task.pid),
            "status": TableCell(task.status, task.status.casefold()),
            "progress": TableCell(
                f"{task.completed}/{task.total}",
                progress,
            ),
            "rate": TableCell(
                "--" if rate is None else f"{rate:.1f}/s",
                -1.0 if rate is None else rate,
            ),
            "failed": TableCell(str(task.failed), task.failed),
            "elapsed": TableCell(
                "--" if elapsed is None else _format_duration(elapsed),
                -1.0 if elapsed is None else elapsed,
            ),
            "started": TableCell(started_text, order_time),
            "group": TableCell(task.group_id, task.group_id.casefold()),
            "command": TableCell(task.command, task.command.casefold()),
        },
        error=task.error,
        log_path=task.log_path,
    )


def _task_metrics(
    task: MonitoredTask,
    current: float,
) -> tuple[float | None, float | None]:
    if task.status == "pending":
        return None, None
    if task.elapsed_seconds is not None:
        return task.elapsed_seconds, task.rate
    if task.started_monotonic is None:
        return None, None
    if task.status in {"done", "error"}:
        if task.finished_monotonic is None:
            return None, None
        end = task.finished_monotonic
    else:
        end = current
    elapsed = max(0.0, end - task.started_monotonic)
    return elapsed, task.completed / elapsed if elapsed else 0.0


class TableReconciler:
    def __init__(self, table: Any):
        self.table = table
        self._cells: dict[str, dict[str, TableCell]] = {}
        self._generation: object = None

    def apply(
        self,
        rows: Iterable[MonitorRow],
        *,
        generation: object,
    ) -> ReconcileResult:
        if generation == self._generation:
            return ReconcileResult(False, frozenset())
        next_rows = {row.key: row for row in rows}
        structure_changed = False
        changed_columns: set[str] = set()

        for key in self._cells.keys() - next_rows.keys():
            self.table.remove_row(key)
            del self._cells[key]
            structure_changed = True

        for key, row in next_rows.items():
            previous = self._cells.get(key)
            if previous is None:
                self.table.add_row(
                    *(row.cells[column] for column, _ in COLUMNS),
                    key=key,
                )
                self._cells[key] = dict(row.cells)
                structure_changed = True
                continue
            for column, value in row.cells.items():
                if previous.get(column) != value:
                    self.table.update_cell(key, column, value)
                    previous[column] = value
                    changed_columns.add(column)

        self._generation = generation
        return ReconcileResult(
            structure_changed,
            frozenset(changed_columns),
        )


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
        provider: Callable[[], MonitorState] = read_monitor_state,
    ):
        super().__init__()
        self._provider = provider
        self._reconciler: TableReconciler | None = None
        self._rows: dict[str, MonitorRow] = {}
        self._sort_column = "started"
        self._sort_reverse = True

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
        state = self._provider()
        rows = [row_from_task(task, now=now) for task in state.tasks]
        self._rows = {row.key: row for row in rows}
        generation = (state.generation, int(now * 2))
        result = self._reconciler.apply(rows, generation=generation)
        if result.structure_changed or self._sort_column in result.changed_columns:
            self._sort_table()
        self.sub_title = f"{len(rows)} groups · 0.2s"

    def on_data_table_header_selected(
        self,
        event: DataTable.HeaderSelected,
    ) -> None:
        selected = str(event.column_key.value)
        if selected == self._sort_column:
            self._sort_reverse = not self._sort_reverse
        else:
            self._sort_column = selected
            self._sort_reverse = False
        self._sort_table()

    def _sort_table(self) -> None:
        table = self.query_one("#tasks", DataTable)
        table.sort(
            self._sort_column,
            key=lambda cell: cell.sort_value,
            reverse=self._sort_reverse,
        )

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
