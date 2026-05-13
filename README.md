# Alpha Common

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/downloads/)
[![Ruff](https://img.shields.io/badge/code%20style-ruff-000000.svg)](https://github.com/astral-sh/ruff)

Aequiludium 共享基础库，为量化研究提供基础设施：交易日历、本地 Parquet 存储引擎、并发框架、ClickHouse 数据库驱动。

---

## 安装

```bash
pip install alpha-common
```

从源码安装（开发模式）：

```bash
git clone https://github.com/Aequiludium/alpha-common.git
cd alpha-common
uv sync
```

---

## 模块

| 模块 | 说明 | 主要功能 |
|------|------|----------|
| `xcals` | 交易日历 | A 股交易日查询、日期偏移、财务报告期计算 |
| `blazestore` | 存储引擎 | 本地 Parquet 文件存储，Hive 分区 + SQL 查询 |
| `ygo` | 并发框架 | 延迟执行 + 线程池 + 进度管理 |
| `clickhouse_df` | 数据库驱动 | ClickHouse 连接与 DataFrame 读写 |

---

## 使用

### xcals — 交易日历

```python
import xcals

# 交易日查询
days = xcals.get_tradingdays("2024-01-01", "2024-12-31")
today = xcals.today()

# 日期偏移
prev = xcals.shift_tradeday("2024-12-31", -5)

# 判断是否为交易日
xcals.is_tradeday("2024-12-31")  # True

# 更新交易日数据
xcals.update()

# Polars 表达式集成（可用于 DataFrame 操作）
import polars as pl
df = pl.DataFrame({"date_str": ["2024-01-01", "2024-01-02"]})
df.with_columns(xcals.to_date("date_str").alias("date"))
```

### blazestore — 本地 Parquet 存储引擎

```python
from blazestore import ParquetStore

store = ParquetStore("/data/store")

# 写入数据（自动 Hive 分区）
store.put("trades", df)

# 读取为 LazyFrame
lf = store.read("trades WHERE date = '2024-01-01'")

# 表管理
store.list_tables()
store.get_table_info("trades")
store.optimize_table("trades")
```

### ygo — 并发框架

```python
from ygo import Pool

pool = Pool()
for day in trading_days:
    pool.submit(download_data, day=day)

results = pool.do()
pool.close()
```

### clickhouse_df — ClickHouse 数据库驱动

```python
from clickhouse_df import to_polars, to_pandas
from clickhouse_df import connect

# 查询到 DataFrame
df = to_polars("SELECT * FROM system.tables")

# 查询到 Pandas
pdf = to_pandas("SELECT * FROM system.tables")

# 批量下载
from clickhouse_df import raw_download
raw_download("SELECT * FROM big_table", "output.csv", {})
```

---

## 开发

```bash
# 安装依赖
uv sync

# 运行测试
uv run pytest tests/

# 代码检查
uv run ruff check .
uv run ruff format --check .
```

---

## 许可证

[MIT](LICENSE)
