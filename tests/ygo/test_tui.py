import asyncio
from dataclasses import replace

from textual.widgets import DataTable

from ygo.monitor import LiveProcess
from ygo.telemetry.model import GroupSnapshot, PoolSnapshot, ProcessSnapshot
from ygo.telemetry.registry import RegistryEntry
from ygo.tui import TableReconciler, YgoTopApp, rows_from_processes


class FakeTable:
    def __init__(self):
        self.calls = []

    def add_row(self, *values, key):
        self.calls.append(("add_row", str(key), values))

    def remove_row(self, key):
        self.calls.append(("remove_row", str(key)))

    def update_cell(self, row_key, column_key, value):
        self.calls.append(("update_cell", str(row_key), str(column_key), value))


def make_live_process(*, completed: int = 4, generation: int = 2) -> LiveProcess:
    group = GroupSnapshot(
        id="quote",
        status="running",
        total=10,
        completed=completed,
        failed=0,
        started_monotonic=90.0,
    )
    snapshot = ProcessSnapshot(
        pid=123,
        process_started_at=1000.0,
        command="python sync.py",
        cwd="/tmp",
        pools=(
            PoolSnapshot(
                id="pool-1",
                backend="threading",
                n_jobs=4,
                status="running",
                groups=(group,),
            ),
        ),
    )
    entry = RegistryEntry(
        pid=123,
        process_started_at=1000.0,
        shared_memory_name="test",
        capacity=4096,
        command="python sync.py",
        cwd="/tmp",
    )
    return LiveProcess(
        entry=entry,
        generation=generation,
        heartbeat_age=0.1,
        snapshot=snapshot,
    )


def test_reconcile_updates_only_changed_cells():
    table = FakeTable()
    reconciler = TableReconciler(table)
    initial = make_live_process()
    reconciler.apply(rows_from_processes([initial], now=100.0), generation=(2,))
    table.calls.clear()
    changed = replace(
        initial,
        generation=4,
        snapshot=replace(
            initial.snapshot,
            pools=(
                replace(
                    initial.snapshot.pools[0],
                    groups=(replace(initial.snapshot.pools[0].groups[0], completed=5),),
                ),
            ),
        ),
    )

    reconciler.apply(rows_from_processes([changed], now=100.0), generation=(4,))

    assert table.calls == [
        ("update_cell", "123:pool-1:quote", "progress", "5/10"),
        ("update_cell", "123:pool-1:quote", "rate", "0.5/s"),
    ]


def test_reconcile_does_nothing_for_same_generation():
    table = FakeTable()
    reconciler = TableReconciler(table)
    rows = rows_from_processes([make_live_process()], now=100.0)
    reconciler.apply(rows, generation=(2,))
    table.calls.clear()

    reconciler.apply(rows, generation=(2,))

    assert table.calls == []


def test_textual_app_keeps_table_mounted_while_cells_change():
    async def exercise():
        state = {"process": make_live_process()}
        app = YgoTopApp(provider=lambda: [state["process"]])
        async with app.run_test() as pilot:
            table = app.query_one("#tasks", DataTable)
            mounted_id = id(table)
            state["process"] = make_live_process(completed=5, generation=4)
            app.refresh_monitor()
            await pilot.pause()

            assert id(app.query_one("#tasks", DataTable)) == mounted_id
            assert table.get_cell("123:pool-1:quote", "progress") == "5/10"

    asyncio.run(exercise())
