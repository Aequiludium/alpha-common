"""
BlazeStore - 本地Parquet存储和数据库集成

提供本地Parquet文件存储、MySQL和ClickHouse数据库集成功能。

Examples:
    >>> from blazestore import ParquetStore, get_settings
    >>> store = ParquetStore()
    >>> store.put(df, "stocks")
    >>> store.put(df, "stocks/2024.parquet")
    >>> store.put(df, "stocks", partitions=["date"])
    >>> df = store.read("stocks").collect()
"""

from ._facade import (
    has,
    list_tables,
    put,
    read,
    sql,
    tb_path,
)
from .clients import (
    download_ck,
    read_ck,
    read_mysql,
    write_mysql,
)
from .config import get_settings
from .store import ParquetStore

__all__ = [
    "download_ck",
    "get_settings",
    "has",
    "list_tables",
    "ParquetStore",
    "put",
    "read",
    "read_ck",
    "read_mysql",
    "sql",
    "tb_path",
    "write_mysql",
]
