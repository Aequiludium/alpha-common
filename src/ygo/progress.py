"""ygo 进度管理器

基于 rich.progress 的任务进度条管理。
"""

from __future__ import annotations

from rich.console import Console
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TaskID,
    TextColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
)
from rich.table import Column


class ProgressManager:
    def __init__(self, show_progress: bool = True):
        self.show_progress = show_progress
        self._progress: Progress | None = None
        self._task_map: dict[str, TaskID] = {}
        self._console = Console()

    def _init_progress(self):
        if self._progress is None and self.show_progress:
            self._progress = Progress(
                SpinnerColumn(),
                TextColumn(
                    "[progress.description]{task.description}",
                    table_column=Column(width=40),
                ),
                BarColumn(),
                MofNCompleteColumn(table_column=Column(width=10)),
                TimeElapsedColumn(table_column=Column(width=10)),
                TimeRemainingColumn(table_column=Column(width=10)),
                console=self._console,
                expand=True,
            )
            self._progress.__enter__()

    def create_task(self, name: str, total: int) -> TaskID | None:
        if not self.show_progress:
            return None
        self._init_progress()
        if self._progress is None:
            return None
        task_id = self._progress.add_task(f"[cyan]{name}", total=total)
        self._task_map[name] = task_id
        return task_id

    def _remove_task(self, task_id: TaskID):
        """移除进度条并清理映射。"""
        self._progress.remove_task(task_id)
        for name, tid in list(self._task_map.items()):
            if tid == task_id:
                del self._task_map[name]

    def update(self, task_id: TaskID | None, advance: int = 1):
        if not self.show_progress or task_id is None or self._progress is None:
            return
        self._progress.update(task_id, advance=advance)
        task = self._progress.tasks[task_id]
        if task.completed >= task.total:
            self._remove_task(task_id)

    def complete(self, task_id: TaskID | None):
        if not self.show_progress or task_id is None or self._progress is None:
            return
        task = self._progress.tasks[task_id]
        self._progress.update(task_id, completed=task.total)
        self._remove_task(task_id)

    def __enter__(self):
        self._init_progress()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self._progress is not None:
            self._progress.__exit__(exc_type, exc_val, exc_tb)
            self._progress = None
