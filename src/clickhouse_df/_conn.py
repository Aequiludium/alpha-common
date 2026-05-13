"""
ClickHouse 连接管理（内部实现）
"""

from __future__ import annotations

import os
from random import randint

from clickhouse_driver import Client

from ._thread import ThreadLocalVariable

_conns = ThreadLocalVariable(default_factory=lambda: [])

_CK_BINARY = os.environ.get("CK_BINARY", os.path.expanduser("~/./clickhouse"))
_CK_DATABASE = os.environ.get("CK_DATABASE", "cquote")


def connect(urls: list[str], user: str, password: str) -> Client:
    """连接 ClickHouse 服务器，支持集群随机负载均衡。

    Args:
        urls: ClickHouse 节点地址列表（host:port 格式）。
        user: 用户名。
        password: 密码。

    Returns:
        创建的 ClickHouse 连接。

    Raises:
        ValueError: urls 为空或地址格式非法时抛出。
    """
    if not urls:
        raise ValueError("urls 参数不能为空")
    i = randint(0, len(urls) - 1)
    url_ini = urls[i]
    try:
        host, port_s = url_ini.split(":")
        port = int(port_s)
    except Exception as e:
        raise ValueError(f"非法的 ClickHouse 地址格式: {url_ini}") from e
    conn = Client(
        host,
        port=port,
        round_robin=True,
        alt_hosts=",".join(urls),
        user=user,
        password=password,
    )
    conns = _conns.get()
    conns.append(conn)
    return conns[-1]


def close_all() -> int:
    """关闭当前线程的所有连接。

    Returns:
        关闭的连接数量。
    """
    conns = _conns.get()
    count = len(conns)
    for conn in conns:
        conn.disconnect()
    conns.clear()
    return count


def _get_default_conn() -> Client:
    """返回当前线程最后一个连接。

    Returns:
        当前线程最后一个活跃连接。

    Raises:
        RuntimeError: 当前线程无活跃连接时抛出。
    """
    conns = _conns.get()
    if not conns:
        raise RuntimeError("No active ClickHouse connection found in current thread.")
    return conns[-1]


def get_cmd_list(settings: dict) -> list[str]:
    """构建 clickhouse-client 命令行参数列表。

    Args:
        settings: 连接配置字典，需包含 urls、user、password 字段。

    Returns:
        clickhouse-client 命令行参数列表。
    """
    host, port = settings["urls"][randint(0, len(settings["urls"]) - 1)].split(":")
    return [
        _CK_BINARY,
        "client",
        "--host",
        host,
        "--port",
        port,
        "--user",
        settings["user"],
        "--database",
        _CK_DATABASE,
        "--password",
        settings["password"],
        "--query",
    ]
