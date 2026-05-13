"""线程本地变量工具（内部实现）。"""

import os
import threading
from typing import Any


class ThreadLocalVariable:
    """线程本地变量。

    Args:
        default_factory: 创建默认值的工厂函数。
        reset_in_subprocess: 是否在子进程中重置变量。
    """

    def __init__(self, default_factory, reset_in_subprocess=True):
        self.reset_in_subprocess = reset_in_subprocess
        self.default_factory = default_factory
        self.thread_local = threading.local()
        # The `__global_thread_values` attribute saves all thread-local values,
        # the key is thread ID.
        self.__global_thread_values: dict[int, Any] = {}

    def get(self):
        """获取线程本地变量值。"""
        if hasattr(self.thread_local, "value"):
            value, pid = self.thread_local.value
            if self.reset_in_subprocess and pid != os.getpid():
                # `get` is called in a forked subprocess, reset it.
                init_value = self.default_factory()
                self.set(init_value)
                return init_value
            else:
                return value
        else:
            init_value = self.default_factory()
            self.set(init_value)
            return init_value

    def set(self, value):
        """设置线程本地变量值。"""
        self.thread_local.value = (value, os.getpid())
        self.__global_thread_values[threading.get_ident()] = value

    def get_all_thread_values(self) -> dict[int, Any]:
        """返回所有线程的值，键为线程 ID。"""
        return self.__global_thread_values.copy()
