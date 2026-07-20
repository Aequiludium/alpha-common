import os
import subprocess
import sys
import time

from ygo.monitor import read_live_snapshots
from ygo.telemetry.registry import RuntimeRegistry

PRODUCER = """
import sys
import time
from pathlib import Path

from ygo import Pool

release = Path(sys.argv[1])
exit_file = Path(sys.argv[2])
pool = Pool(n_jobs=1, show_progress=False)
print(pool._pool_id, flush=True)

def work():
    while not release.exists():
        time.sleep(0.02)
    return 1

pool.submit(work, job_name="quote")()
pool.do()
print("DONE", flush=True)
while not exit_file.exists():
    time.sleep(0.02)
"""


def wait_until(predicate, *, timeout: float = 5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.02)
    raise AssertionError("condition not met before timeout")


def test_subprocess_pool_is_discoverable_and_cleans_up(tmp_path):
    runtime_dir = tmp_path / "runtime"
    registry = RuntimeRegistry(runtime_dir)
    release = tmp_path / "release"
    exit_file = tmp_path / "exit"
    env = dict(os.environ)
    env["YGO_RUNTIME_DIR"] = str(runtime_dir)
    process = subprocess.Popen(
        [sys.executable, "-c", PRODUCER, str(release), str(exit_file)],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert process.stdout is not None
        pool_id = process.stdout.readline().strip()
        assert pool_id

        discovered = wait_until(lambda: read_live_snapshots(registry))
        group = discovered[0].snapshot.pools[0].groups[0]
        assert group.id == "quote"
        assert group.status == "pending"
        assert group.finished_monotonic is None

        release.touch()
        assert process.stdout.readline().strip() == "DONE"

        def completed_group():
            records = read_live_snapshots(registry)
            if not records:
                return None
            current = records[0].snapshot.pools[0].groups[0]
            return current if current.status == "done" else None

        completed = wait_until(completed_group)
        assert completed.completed == 1
        assert completed.finished_monotonic >= completed.started_monotonic
        exit_file.touch()
        stdout, stderr = process.communicate(timeout=5)
        assert process.returncode == 0, f"{stdout}\n{stderr}"
        wait_until(lambda: not registry.entries())
    finally:
        exit_file.touch()
        if process.poll() is None:
            process.terminate()
            process.wait(timeout=5)
