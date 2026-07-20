from ygo import cli as cli_module
from ygo.cli import main
from ygo.monitor import LiveProcess
from ygo.telemetry.model import GroupSnapshot, PoolSnapshot, ProcessSnapshot
from ygo.telemetry.registry import RegistryEntry


def make_live_process() -> LiveProcess:
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
                groups=(
                    GroupSnapshot(
                        id="quote",
                        status="running",
                        total=10,
                        completed=4,
                        failed=1,
                        started_monotonic=90.0,
                        last_error="timeout",
                    ),
                ),
            ),
        ),
    )
    return LiveProcess(
        entry=RegistryEntry(
            pid=123,
            process_started_at=1000.0,
            shared_memory_name="test",
            capacity=4096,
            command="python sync.py",
            cwd="/tmp",
        ),
        generation=2,
        heartbeat_age=0.1,
        snapshot=snapshot,
    )


def test_ps_prints_live_groups(monkeypatch, capsys):
    monkeypatch.setattr("ygo.cli.read_live_snapshots", lambda: [make_live_process()])

    assert main(["ps"]) == 0

    output = capsys.readouterr().out
    assert "quote" in output
    assert "4/10" in output


def test_top_prepares_shared_memory_before_textual_starts(monkeypatch):
    events = []

    class FakeApp:
        def run(self):
            events.append("run")

    monkeypatch.setattr(
        cli_module,
        "prepare_reader_process",
        lambda: events.append("prepare"),
    )
    monkeypatch.setattr(cli_module, "YgoTopApp", FakeApp)

    assert main(["top"]) == 0
    assert events == ["prepare", "run"]


def test_show_and_errors_select_pool(monkeypatch, capsys):
    monkeypatch.setattr("ygo.cli.read_live_snapshots", lambda: [make_live_process()])

    assert main(["show", "pool-1"]) == 0
    assert "threading" in capsys.readouterr().out
    assert main(["errors", "pool-1"]) == 0
    assert "timeout" in capsys.readouterr().out


def test_show_returns_one_for_missing_pool(monkeypatch):
    monkeypatch.setattr("ygo.cli.read_live_snapshots", lambda: [])

    assert main(["show", "missing"]) == 1
