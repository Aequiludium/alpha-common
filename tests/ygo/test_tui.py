import asyncio
import datetime
from dataclasses import replace
from types import SimpleNamespace

from textual.widgets import DataTable

from ygo.monitor import MonitoredTask, MonitorState
from ygo.tui import TableReconciler, YgoTopApp, row_from_task


class FakeTable:
    def __init__(self):
        self.calls = []

    def add_row(self, *values, key):
        self.calls.append(("add_row", str(key), values))

    def remove_row(self, key):
        self.calls.append(("remove_row", str(key)))

    def update_cell(self, row_key, column_key, value):
        self.calls.append(("update_cell", str(row_key), str(column_key), value))


def make_task(
    *,
    key: str = "task-123",
    pid: int = 123,
    completed: int = 4,
    total: int = 10,
    status: str = "running",
    registered_at: float = 1000.0,
    started_at: float | None = 1001.0,
    finished_at: float | None = None,
    started_monotonic: float | None = 90.0,
    finished_monotonic: float | None = None,
    elapsed_seconds: float | None = None,
    rate: float | None = None,
    group_id: str = "quote",
) -> MonitoredTask:
    return MonitoredTask(
        key=key,
        pid=pid,
        status=status,
        completed=completed,
        total=total,
        failed=0,
        registered_at=registered_at,
        started_at=started_at,
        finished_at=finished_at,
        started_monotonic=started_monotonic,
        finished_monotonic=finished_monotonic,
        elapsed_seconds=elapsed_seconds,
        rate=rate,
        group_id=group_id,
        command="python sync.py",
        error=None,
        log_path=None,
    )


def row_order(table: DataTable) -> list[str]:
    return [str(row.key.value) for row in table.ordered_rows]


def test_reconcile_updates_only_changed_cells():
    table = FakeTable()
    reconciler = TableReconciler(table)
    initial = row_from_task(make_task(), now=100.0)
    reconciler.apply([initial], generation=(2,))
    table.calls.clear()
    changed = row_from_task(make_task(completed=5), now=100.0)

    result = reconciler.apply([changed], generation=(4,))

    assert [(call[0], call[1], call[2], call[3].text) for call in table.calls] == [
        ("update_cell", "task-123", "progress", "5/10"),
        ("update_cell", "task-123", "rate", "0.5/s"),
    ]
    assert result.structure_changed is False
    assert result.changed_columns == frozenset({"progress", "rate"})


def test_reconcile_does_nothing_for_same_generation():
    table = FakeTable()
    reconciler = TableReconciler(table)
    rows = [row_from_task(make_task(), now=100.0)]
    reconciler.apply(rows, generation=(2,))
    table.calls.clear()

    result = reconciler.apply(rows, generation=(2,))

    assert table.calls == []
    assert result.structure_changed is False
    assert result.changed_columns == frozenset()


def test_pending_group_hides_metrics_but_sorts_by_registration():
    task = make_task(
        completed=0,
        status="pending",
        started_at=None,
        started_monotonic=None,
    )

    row = row_from_task(task, now=100.0)

    assert row.cells["rate"].text == "--"
    assert row.cells["elapsed"].text == "--"
    assert row.cells["started"].text == "--"
    assert row.cells["started"].sort_value == 1000.0


def test_done_group_uses_frozen_history_metrics():
    task = make_task(
        completed=10,
        status="done",
        started_at=1001.0,
        finished_at=1006.0,
        started_monotonic=None,
        elapsed_seconds=5.0,
        rate=2.0,
    )

    first = row_from_task(task, now=100.0)
    later = row_from_task(task, now=200.0)

    assert first.cells["rate"].text == "2.0/s"
    assert first.cells["elapsed"].text == "00:00:05"
    assert later.cells["rate"] == first.cells["rate"]
    assert later.cells["elapsed"] == first.cells["elapsed"]


def test_started_uses_local_time_and_columns_use_typed_sort_values():
    timestamp = 1_760_000_000.0
    row = row_from_task(
        make_task(
            pid=20,
            completed=9,
            total=10,
            registered_at=timestamp - 1,
            started_at=timestamp,
        ),
        now=100.0,
    )
    smaller_progress = row_from_task(
        make_task(key="small", pid=100, completed=10, total=100),
        now=100.0,
    )

    assert row.cells["started"].text == datetime.datetime.fromtimestamp(timestamp).strftime(
        "%Y-%m-%d %H:%M:%S"
    )
    assert row.cells["started"].sort_value == timestamp
    assert row.cells["pid"].sort_value == 20
    assert smaller_progress.cells["pid"].sort_value == 100
    assert row.cells["progress"].sort_value == 0.9
    assert smaller_progress.cells["progress"].sort_value == 0.1


def test_textual_app_sorts_newest_first_and_toggles_header_direction():
    async def exercise():
        older = make_task(
            key="older",
            pid=20,
            registered_at=1000.0,
            started_at=1001.0,
        )
        newer = make_task(
            key="newer",
            pid=100,
            registered_at=2000.0,
            started_at=2001.0,
        )
        state = {"value": MonitorState(tasks=(older, newer), generation=1)}
        app = YgoTopApp(provider=lambda: state["value"])
        async with app.run_test() as pilot:
            table = app.query_one("#tasks", DataTable)
            mounted_id = id(table)
            assert row_order(table) == ["newer", "older"]

            newest = make_task(
                key="newest",
                pid=50,
                registered_at=3000.0,
                started_at=3001.0,
            )
            state["value"] = MonitorState(
                tasks=(older, newer, newest),
                generation=2,
            )
            app.refresh_monitor()
            await pilot.pause()
            assert row_order(table) == ["newest", "newer", "older"]

            pid_header = SimpleNamespace(
                column_key=SimpleNamespace(value="pid"),
            )
            app.on_data_table_header_selected(pid_header)
            assert row_order(table) == ["older", "newest", "newer"]
            app.on_data_table_header_selected(pid_header)
            assert row_order(table) == ["newer", "newest", "older"]

            state["value"] = MonitorState(
                tasks=(older, replace(newer, completed=5), newest),
                generation=3,
            )
            app.refresh_monitor()
            await pilot.pause()

            assert id(app.query_one("#tasks", DataTable)) == mounted_id
            assert table.get_cell("newer", "progress").text == "5/10"

    asyncio.run(exercise())
