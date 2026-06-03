# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Build & Test Commands

```bash
# Install dependencies
uv sync

# Run all tests
uv run pytest tests/

# Lint & format
uv run ruff check .
uv run ruff check . --fix
uv run ruff format .
uv run ruff format --check .

# Build package
uv build
```

## Architecture Overview

This is **alpha-common** — a Python library providing infrastructure for quantitative trading research. It has four independent modules under `src/`:

### xcals — Trading Calendar
A-share (Chinese stock market) trading calendar. Singleton `Calendar` class loads date data from `~/.xcals` (falls back to bundled `.xcals`). Uses `bisect` for O(log n) date lookups. Provides Polars expression generators (`to_date`, `to_datetime`, `to_time`), report period calculation with disclosure deadline safety checks, and time series generation that excludes lunch breaks.

Key file: `src/xcals/calendar.py` — public API; `src/xcals/_store.py` — `Calendar` singleton implementation.

### blazestore — Parquet Storage Engine
Local Parquet file storage built on Polars. Supports three write modes: direct `.parquet` file, directory with `data.parquet`, and Hive-style partitioning. `ParquetStore` class handles all operations; a module-level facade (`_facade.py`) provides convenience functions. SQL queries against local Parquet files are supported via `sql()` which rewrites table references to `read_parquet()` calls. For partitioned tables, it uses `pl.SQLContext` with `hive_partitioning=True`.

Database clients (`blazestore/clients/`): `MySQLClient` (read/write via `pl.read_database_uri`/`write_database`) and `ClickHouseClient` (read via `clickhouse_df`). Configuration via `Dynaconf` at `~/.blaze/config.toml`.

Exception hierarchy: `BlazeStoreError` → `ConfigError`, `DatabaseError` (`ConnectionError`, `QueryError`, `WriteError`), `StorageError` (`FileOperationError`, `PathError`, `PartitionError`).

### ygo — Concurrency Framework
Joblib-based parallel task pool. `Pool` class collects `DelayedFunction` tasks (grouped by name) and executes them via joblib's `Parallel` with `generator_unordered`. Supports threading/multiprocessing backends. Optional Rich progress bars (`ProgressManager`). Tasks use lazy binding: `delay(fn)(args...)` creates a deferred call, `.bind(**kwargs)` fixes arguments.

### clickhouse_df — ClickHouse Driver
Connection management (thread-local, random load-balanced node selection via `randint`). Query results to Polars DataFrame (via pyarrow) or Pandas. `raw_download()` pipes through the `clickhouse-client` binary for large result sets. Type mapping from ClickHouse types to Arrow types in `_dtype.py`.

## Key Patterns

- **Lazy by default**: Polars `LazyFrame` preferred over eager `DataFrame`; `blazestore.read()` returns `LazyFrame`, `sql()` defaults to `lazy=True`
- **All times in Asia/Shanghai**: Stock data uses China timezone
- **Config via filesystem + env**: `~/.blaze/config.toml` for blazestore paths and database credentials; `CK_BINARY`/`CK_DATABASE` env vars for clickhouse_df
- **Thread-safe ClickHouse connections**: Thread-local storage via `ThreadLocalVariable`
- **Conventional commits**: feat/fix/docs/refactor/test/chore prefixes
