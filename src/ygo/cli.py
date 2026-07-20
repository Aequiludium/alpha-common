from __future__ import annotations

import argparse
import os
import subprocess
from collections.abc import Sequence

from rich.console import Console
from rich.table import Table

from .monitor import LiveProcess, read_live_snapshots
from .telemetry.model import PoolSnapshot
from .tui import YgoTopApp


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="ygo", description="Monitor local ygo tasks")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("top", help="Open the interactive task dashboard")
    commands.add_parser("ps", help="List live task groups")
    for name in ("show", "errors"):
        command = commands.add_parser(name)
        command.add_argument("pool_id")
    run = commands.add_parser("run", help="Run a monitored command")
    run.add_argument("args", nargs=argparse.REMAINDER)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "top":
        YgoTopApp().run()
        return 0
    if args.command == "run":
        command = list(args.args)
        if command[:1] == ["--"]:
            command = command[1:]
        if not command:
            build_parser().error("ygo run requires a command after --")
        env = dict(os.environ)
        env.setdefault("YGO_MONITOR", "1")
        return subprocess.call(command, env=env)

    processes = read_live_snapshots()
    console = Console()
    if args.command == "ps":
        console.print(_process_table(processes))
        return 0

    selected = _find_pool(processes, args.pool_id)
    if selected is None:
        console.print(f"[red]unknown live pool:[/] {args.pool_id}")
        return 1
    process, pool = selected
    if args.command == "show":
        _print_pool(console, process, pool)
    else:
        _print_errors(console, process, pool)
    return 0


def _process_table(processes: list[LiveProcess]) -> Table:
    table = Table(title="ygo live tasks")
    for label in ("PID", "STATUS", "PROGRESS", "FAIL", "GROUP", "POOL", "COMMAND"):
        table.add_column(label)
    for process in processes:
        for pool in process.snapshot.pools:
            for group in pool.groups:
                table.add_row(
                    str(process.snapshot.pid),
                    group.status,
                    f"{group.completed}/{group.total}",
                    str(group.failed),
                    group.id,
                    pool.id,
                    process.entry.command,
                )
    return table


def _find_pool(
    processes: list[LiveProcess],
    pool_id: str,
) -> tuple[LiveProcess, PoolSnapshot] | None:
    for process in processes:
        for pool in process.snapshot.pools:
            if pool.id == pool_id:
                return process, pool
    return None


def _print_pool(console: Console, process: LiveProcess, pool: PoolSnapshot) -> None:
    console.print(f"[bold]pool[/] {pool.id}")
    console.print(f"pid={process.snapshot.pid}")
    console.print(f"backend={pool.backend}")
    console.print(f"n_jobs={pool.n_jobs}")
    console.print(f"status={pool.status}")
    console.print(f"heartbeat_age={process.heartbeat_age:.1f}s")
    for group in pool.groups:
        console.print(
            f"{group.id} status={group.status} progress={group.completed}/{group.total} "
            f"failed={group.failed}"
        )


def _print_errors(console: Console, process: LiveProcess, pool: PoolSnapshot) -> None:
    del process
    errors = [group for group in pool.groups if group.last_error]
    if not errors:
        console.print("No captured errors")
        return
    for group in errors:
        console.print(f"[red]{group.id}[/]: {group.last_error}")


if __name__ == "__main__":
    raise SystemExit(main())
