import os
from dataclasses import replace

import pytest

from ygo.telemetry.history import HistoryRecord, HistoryStore, make_task_key


def make_record(index: int) -> HistoryRecord:
    return HistoryRecord(
        task_key=f"42:1000000000:pool:{index}",
        pid=42,
        process_started_at=1.0,
        pool_id="pool",
        group_id=f"group-{index}",
        command="python sync.py",
        status="done",
        total=10,
        completed=10,
        failed=0,
        last_error=None,
        log_path=None,
        registered_at=1000.0 + index,
        started_at=1001.0 + index,
        finished_at=1006.0 + index,
        elapsed_seconds=5.0,
        rate=2.0,
    )


def test_history_round_trip_and_stable_task_key(tmp_path):
    store = HistoryStore(tmp_path)
    record = make_record(1)

    store.append(record)

    assert store.recent() == [record]
    assert make_task_key(42, 1.5, "pool", "group") == "42:1500000000:pool:group"


def test_history_overwrites_same_task_without_duplication(tmp_path):
    store = HistoryStore(tmp_path)
    original = make_record(1)
    updated = replace(original, finished_at=2000.0, rate=3.0)

    store.append(original)
    store.append(updated)

    assert store.recent() == [updated]
    assert len(list(tmp_path.glob("*.json"))) == 1


def test_history_retains_latest_100_records(tmp_path):
    store = HistoryStore(tmp_path)

    for index in range(105):
        store.append(make_record(index))

    records = store.recent()

    assert len(records) == 100
    assert records[0].group_id == "group-104"
    assert records[-1].group_id == "group-5"
    assert len(list(tmp_path.glob("*.json"))) == 100


def test_history_ignores_malformed_records(tmp_path):
    store = HistoryStore(tmp_path)
    store.append(make_record(1))
    (tmp_path / "broken.json").write_text("{", encoding="utf-8")

    assert store.recent() == [make_record(1)]


@pytest.mark.skipif(os.name == "nt", reason="POSIX permission bits are unavailable")
def test_history_uses_private_permissions(tmp_path):
    root = tmp_path / "history"
    store = HistoryStore(root)

    store.append(make_record(1))

    assert root.stat().st_mode & 0o777 == 0o700
    record_path = next(root.glob("*.json"))
    assert record_path.stat().st_mode & 0o777 == 0o600


def test_default_history_honors_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("YGO_HISTORY_DIR", str(tmp_path))

    assert HistoryStore().root == tmp_path
