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
        self._task_names: dict[TaskID, str] = {}
        self._failed_tasks: set[TaskID] = set()
        self._console = Console()

    def _init_progress(self):
        if self._progress is None and self.show_progress:
            self._progress = Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(table_column=Column(width=30)),
                MofNCompleteColumn(table_column=Column(width=10)),
                TimeElapsedColumn(table_column=Column(width=10)),
                TimeRemainingColumn(table_column=Column(width=10)),
                console=self._console,
                expand=False,
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
        self._task_names[task_id] = name
        return task_id

    def update(self, task_id: TaskID | None, advance: int = 1):
        if not self.show_progress or task_id is None or self._progress is None:
            return
        self._progress.update(task_id, advance=advance)
        task = self._progress.tasks[task_id]
        if task.completed >= task.total:
            name = self._task_names.get(task_id)
            if name is None:
                return
            if task_id in self._failed_tasks:
                self._progress.update(task_id, description=f"[red]✗ {name}")
            else:
                self._progress.update(task_id, description=f"[green]✓ {name}")

    def mark_failure(self, task_id: TaskID | None):
        """标记任务组中有任务失败，进度条变红。"""
        if not self.show_progress or task_id is None or self._progress is None:
            return
        self._failed_tasks.add(task_id)
        name = self._task_names.get(task_id)
        if name is not None:
            self._progress.update(task_id, description=f"[red]✗ {name}")

    def complete(self, task_id: TaskID | None):
        if not self.show_progress or task_id is None or self._progress is None:
            return
        task = self._progress.tasks[task_id]
        self._progress.update(task_id, completed=task.total)
        name = self._task_names.get(task_id)
        if name is None:
            return
        if task_id in self._failed_tasks:
            self._progress.update(task_id, description=f"[red]✗ {name}")
        else:
            self._progress.update(task_id, description=f"[green]✓ {name}")

    def __enter__(self):
        self._init_progress()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self._progress is not None:
            self._progress.__exit__(exc_type, exc_val, exc_tb)
            self._progress = None
