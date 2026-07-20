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
    publisher.record_completion("p1", "quote", failed=False)
    publisher.record_completion("p1", "quote", failed=True, error="timeout")

    assert transport.write_count == 1
    clock.advance(0.1)
    publisher.tick()
    assert transport.write_count == 2
    group = transport.last.pools[0].groups[0]
    assert group.completed == 2
    assert group.failed == 1
    assert group.last_error == "timeout"


def test_complete_pool_forces_final_snapshot():
    transport = FakeTransport()
    publisher = TelemetryPublisher(transport=transport, start_thread=False)
    publisher.register_pool("p1", backend="threading", n_jobs=1, groups={"g": 1})
    publisher.record_completion("p1", "g", failed=False)

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
    publisher.record_completion("p1", "g", failed=False)
    publisher.tick()

    assert len(warnings) == 1


def test_close_is_idempotent():
    transport = FakeTransport()
    publisher = TelemetryPublisher(transport=transport, start_thread=False)

    publisher.close()
    publisher.close()

    assert transport.closed is True
