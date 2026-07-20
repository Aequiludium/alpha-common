import json

import pytest

from ygo.telemetry.model import GroupSnapshot, PoolSnapshot, ProcessSnapshot


def test_process_snapshot_round_trip():
    snapshot = ProcessSnapshot(
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
                        finished_monotonic=25.0,
                        last_error="timeout",
                    ),
                ),
            ),
        ),
    )

    assert ProcessSnapshot.from_json(snapshot.to_json()) == snapshot


def test_snapshot_accepts_group_without_finish_timestamp():
    snapshot = ProcessSnapshot(
        pid=123,
        process_started_at=1000.5,
        command="python sync.py",
        cwd="/tmp/work",
        pools=(
            PoolSnapshot(
                id="pool-1",
                backend="threading",
                n_jobs=1,
                status="running",
                groups=(
                    GroupSnapshot(
                        id="quote",
                        status="pending",
                        total=1,
                        completed=0,
                        failed=0,
                        started_monotonic=20.0,
                    ),
                ),
            ),
        ),
    )

    assert ProcessSnapshot.from_json(snapshot.to_json()) == snapshot

    payload = json.loads(snapshot.to_json())
    del payload["pools"][0]["groups"][0]["finished_monotonic"]
    assert ProcessSnapshot.from_json(json.dumps(payload)) == snapshot


def test_snapshot_rejects_incompatible_schema():
    payload = json.dumps(
        {
            "schema_version": 999,
            "pid": 1,
            "process_started_at": 1,
            "command": "",
            "cwd": "",
            "pools": [],
        }
    )

    with pytest.raises(ValueError, match="schema"):
        ProcessSnapshot.from_json(payload)


def test_snapshot_rejects_malformed_nested_payload():
    payload = json.dumps(
        {
            "schema_version": 1,
            "pid": 1,
            "process_started_at": 1,
            "command": "",
            "cwd": "",
            "pools": [{"id": "pool"}],
        }
    )

    with pytest.raises(ValueError, match="snapshot"):
        ProcessSnapshot.from_json(payload)
