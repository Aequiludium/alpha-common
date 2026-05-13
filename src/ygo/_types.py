"""ygo 类型定义

定义任务执行器协议接口，支持可替换的执行后端。
"""

from collections.abc import Callable
from typing import Protocol, TypeVar

T = TypeVar("T")


class Executor(Protocol):
    """可替换的任务执行接口，兼容 Pool 和未来后端。"""

    def submit(
        self, fn: Callable[..., T], job_name: str | None = None
    ) -> Callable[..., object]: ...

    def map(self, fn: Callable[..., T], *iterables) -> list[T]: ...
