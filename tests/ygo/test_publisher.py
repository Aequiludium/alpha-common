from dataclasses import dataclass

from ygo.telemetry.publisher import TelemetryPublisher


@dataclass
class FakeClock:
    value: float = 100.0

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


class FakeTransport:
    def __init__(self, *, fail: bool = False):
        self.fail = fail
        self.snapshots = []
        self.closed = False

    @property
    def write_count(self) -> int:
        return len(self.snapshots)

    @property
    def last(self):
        return self.snapshots[-1]

    def write(self, snapshot, *, heartbeat_ns=None):
        if self.fail:
            raise OSError("transport failed")
        self.snapshots.append(snapshot)
        return len(self.snapshots) * 2

    def close(self):
        self.closed = True

    def unlink(self):
        pass


def test_publisher_coalesces_updates():
    clock = FakeClock()
    transport = FakeTransport()
    publisher = TelemetryPublisher(
        transport=transport,
        clock=clock,
        start_thread=False,
    )

    publisher.register_pool("p1", backend="threading", n_jobs=4, groups={"quote": 10})
    publisher.record_completion(
        "p1",
        "quote",
        failed=False,
        started_monotonic=101.0,
        finished_monotonic=102.0,
    )
    publisher.record_completion(
        "p1",
        "quote",
        failed=True,
        error="timeout",
        started_monotonic=103.0,
        finished_monotonic=104.0,
    )

    assert transport.write_count == 1
    clock.advance(0.1)
    publisher.tick()
    assert transport.write_count == 2
    group = transport.last.pools[0].groups[0]
    assert group.completed == 2
    assert group.failed == 1
    assert group.last_error == "timeout"
    assert group.status == "running"
    assert group.started_monotonic == 101.0
    assert group.finished_monotonic is None


def test_groups_are_pending_until_results_arrive_and_terminal_times_are_captured():
    clock = FakeClock()
    transport = FakeTransport()
    publisher = TelemetryPublisher(
        transport=transport,
        clock=clock,
        start_thread=False,
    )

    publisher.register_pool(
        "p1",
        backend="threading",
        n_jobs=1,
        groups={"first": 1, "later": 1},
    )

    first, later = transport.last.pools[0].groups
    assert first.status == "pending"
    assert later.status == "pending"

    publisher.record_completion(
        "p1",
        "first",
        failed=False,
        started_monotonic=102.0,
        finished_monotonic=105.0,
    )
    clock.advance(0.1)
    publisher.tick()

    first, later = transport.last.pools[0].groups
    assert first.status == "done"
    assert first.started_monotonic == 102.0
    assert first.finished_monotonic == 105.0
    assert later.status == "pending"
    assert later.finished_monotonic is None


def test_complete_pool_forces_final_snapshot():
    transport = FakeTransport()
    publisher = TelemetryPublisher(transport=transport, start_thread=False)
    publisher.register_pool("p1", backend="threading", n_jobs=1, groups={"g": 1})
    publisher.record_completion(
        "p1",
        "g",
        failed=False,
        started_monotonic=100.0,
        finished_monotonic=101.0,
    )

    publisher.complete_pool("p1")

    assert transport.last.pools[0].status == "done"
    assert transport.last.pools[0].groups[0].status == "done"


def test_publisher_swallows_transport_failure():
    warnings = []
    publisher = TelemetryPublisher(
        transport=FakeTransport(fail=True),
        start_thread=False,
        warn=warnings.append,
    )

    publisher.register_pool("p1", backend="threading", n_jobs=1, groups={"g": 1})
    publisher.record_completion(
        "p1",
        "g",
        failed=False,
        started_monotonic=100.0,
        finished_monotonic=101.0,
    )
    publisher.tick()

    assert len(warnings) == 1


def test_close_is_idempotent():
    transport = FakeTransport()
    publisher = TelemetryPublisher(transport=transport, start_thread=False)

    publisher.close()
    publisher.close()

    assert transport.closed is True
