"""
ClickHouse 查询接口
"""

from __future__ import annotations

from subprocess import PIPE, Popen

import pandas as pd
import polars as pl
import pyarrow as pa
from clickhouse_driver import Client

from . import _dtype as dtype
from ._conn import _get_default_conn, get_cmd_list


def to_pandas(sql: str, conn: Client | None = None) -> pd.DataFrame:
    """执行 SQL 查询，返回 pandas DataFrame。

    Args:
        sql: SQL 查询语句。
        conn: ClickHouse 连接，默认为当前线程最后一个连接。

    Returns:
        查询结果的 pandas DataFrame。
    """
    conn = conn if conn is not None else _get_default_conn()
    return conn.query_dataframe(sql)


def to_polars(sql: str, conn: Client | None = None) -> pl.DataFrame:
    """执行 SQL 查询，返回 polars DataFrame。

    Args:
        sql: SQL 查询语句。
        conn: ClickHouse 连接，默认为当前线程最后一个连接。

    Returns:
        查询结果的 polars DataFrame。
    """
    conn = conn if conn is not None else _get_default_conn()
    data, columns = conn.execute(sql, columnar=True, with_column_types=True)
    if len(data) < 1:
        field_types = {
            name: dtype.map_clickhouse_to_arrow(type_) for name, type_ in columns
        }
        arrays = [pa.array([], type=col_type) for col_type in field_types.values()]
        arrow_table = pa.Table.from_arrays(arrays, schema=pa.schema(field_types))
        return pl.from_arrow(arrow_table)

    field_types = {
        name: dtype.map_clickhouse_to_arrow(type_) for name, type_ in columns
    }
    arrow_table = pa.Table.from_arrays(
        [
            pa.array(col, type=col_type)
            for col, col_type in zip(data, field_types.values(), strict=False)
        ],
        schema=pa.schema(field_types),
    )
    return pl.from_arrow(arrow_table)


def raw_download(sql: str, output_file: str, settings: dict) -> None:
    """通过 clickhouse-client 命令行将查询结果写入 Parquet 文件。

    Args:
        sql: SQL 查询语句，末尾不能包含分号。
        output_file: 输出 Parquet 文件路径。
        settings: ClickHouse 连接配置。

    Raises:
        ValueError: SQL 末尾包含分号时抛出。
    """
    sql = sql.rstrip()
    if sql.endswith(";"):
        raise ValueError("SQL 末尾不允许分号 ';'，请移除后再执行")
    inner = f"""
    SELECT * FROM ({sql})
    INTO OUTFILE '{output_file}' TRUNCATE
    FORMAT Parquet
    """
    cmd_list = get_cmd_list(settings)
    cmd_list.append(inner)
    p = Popen(cmd_list, stdin=PIPE, stdout=PIPE)
    for _ in p.stdout:
        pass
