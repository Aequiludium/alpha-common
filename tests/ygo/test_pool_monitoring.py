from ygo import Pool


class FakePublisher:
    def __init__(self):
        self.pool_id = None
        self.registered_groups = {}
        self.completions = []
        self.completed = False

    def register_pool(self, pool_id, *, backend, n_jobs, groups):
        self.pool_id = pool_id
        self.registered_groups = groups

    def record_completion(
        self,
        pool_id,
        group_id,
        *,
        failed,
        error=None,
        started_monotonic,
        finished_monotonic,
    ):
        assert pool_id == self.pool_id
        self.completions.append((group_id, failed, error, started_monotonic, finished_monotonic))

    def complete_pool(self, pool_id):
        assert pool_id == self.pool_id
        self.completed = True


def test_pool_publishes_group_progress():
    publisher = FakePublisher()
    pool = Pool(
        n_jobs=1,
        show_progress=False,
        monitor=True,
        _publisher=publisher,
    )
    pool.submit(lambda value: value, job_name="quote")(value=1)
    pool.submit(lambda value: value, job_name="quote")(value=2)

    assert pool.do() == [1, 2]
    assert publisher.registered_groups == {"quote": 2}
    assert [(group, failed, error) for group, failed, error, _, _ in publisher.completions] == [
        ("quote", False, None),
        ("quote", False, None),
    ]
    assert all(start <= finish for _, _, _, start, finish in publisher.completions)
    assert publisher.completed is True


def test_show_progress_false_does_not_disable_monitor():
    publisher = FakePublisher()
    pool = Pool(show_progress=False, monitor=True, _publisher=publisher)
    pool.submit(lambda: 1, job_name="g")()

    pool.do()

    assert publisher.registered_groups == {"g": 1}


def test_pool_publishes_failure_summary():
    publisher = FakePublisher()
    pool = Pool(n_jobs=1, show_progress=False, _publisher=publisher)

    def fail():
        raise ValueError("boom")

    pool.submit(fail, job_name="broken")()

    assert pool.do() == [None]
    assert [(group, failed, error) for group, failed, error, _, _ in publisher.completions] == [
        ("broken", True, "ValueError: boom")
    ]
