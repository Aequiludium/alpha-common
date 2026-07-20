from ygo import delay
from ygo._pool import multi_task_name


class FakeProgressManager:
    instances = []

    def __init__(self, show_progress=True):
        self.created = []
        self.updates = []
        self.failures = []
        self.__class__.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass

    def create_task(self, name, total):
        self.created.append((name, total))
        return 7

    def update(self, task_id, advance=1):
        self.updates.append((task_id, advance))

    def mark_failure(self, task_id):
        self.failures.append(task_id)


def test_multiple_groups_use_one_inline_progress_row(monkeypatch):
    monkeypatch.setattr("ygo._pool.ProgressManager", FakeProgressManager)
    jobs = {
        "quote": [delay(lambda: 1).bind()],
        "financial": [delay(lambda: 2).bind()],
    }

    assert multi_task_name(jobs, 1, "threading", True) == {
        "quote": [1],
        "financial": [2],
    }

    progress = FakeProgressManager.instances[-1]
    assert progress.created == [("ygo", 2)]
    assert progress.updates == [(7, 1), (7, 1)]
