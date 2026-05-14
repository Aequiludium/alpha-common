# Alpha Common

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/downloads/)
[![Ruff](https://img.shields.io/badge/code%20style-ruff-000000.svg)](https://github.com/astral-sh/ruff)

Alpha 策略研究基础设施库，提供量化研究中常用的四个核心模块：

- **xcals** — A 股交易日历（交易日查询、日期偏移、报告期计算）
- **blazestore** — 本地 Parquet 存储引擎（Hive 分区、SQL 查询、MySQL/ClickHouse 客户端）
- **ygo** — 并发任务框架（延迟执行、线程池、进度条）
- **clickhouse_df** — ClickHouse 数据库驱动（Polars/Pandas 读写、命令行批量下载）

---

## 安装

```bash
pip install alpha-common
```

开发模式（使用 uv）：

```bash
git clone https://github.com/Aequiludium/alpha-common.git
cd alpha-common
uv sync
```

---

## 使用

### xcals — 交易日历

```python
import xcals

# 交易日查询
days = xcals.get_tradingdays("2024-01-01", "2024-12-31")
# -> ['2024-01-02', '2024-01-03', ..., '2024-12-31']

xcals.is_tradeday("2024-12-31")  # True

# 日期偏移（非交易日自动跳到最近交易日）
prev = xcals.shift_tradeday("2024-12-31", -5)
# -> '2024-12-24'

# 最近交易日
xcals.get_last_tradingday("2024-01-01")
# -> '2023-12-29'

# 报告期计算（获取前 2 个季报截止日）
xcals.get_previous_report_dates("2024-10-15", n=2)
# -> ['2024-06-30', '2024-03-31']

# 更新交易日数据（从远程下载最新日历）
xcals.update()
```

---

### blazestore — 本地 Parquet 存储引擎

支持三种写入模式和 SQL 查询，配置路径默认为 `~/.blaze/config.toml`。

#### 模块级 API（推荐）

```python
from blazestore import put, read, sql, list_tables

# 写入：自动识别模式
put(df, "trades")                          # 写入 trades/data.parquet
put(df, "trades/2024.parquet")             # 直接写入文件
put(df, "trades", partitions=["date"])     # Hive 分区写入

# 读取（返回 LazyFrame，自动识别 Hive 分区）
lf = read("trades")
df = lf.filter(pl.col("symbol") == "AAPL").collect()

# 对本地 Parquet 文件执行 SQL 查询
result = sql("SELECT date, count(*) FROM trades GROUP BY date")
```

#### 类 API

```python
from blazestore import ParquetStore

store = ParquetStore("/data/store")

# 写入
store.put(df, "trades")
store.put(df, "trades", partitions=["date"])

# 读取
lf = store.read("trades")

# 表管理
store.list_tables()              # -> ['trades', 'orders']
store.get_table_info("trades")   # -> {'name': 'trades', 'rows': 1000, ...}
store.optimize_table("trades")   # 合并小文件
store.check_table("trades")      # -> True
store.delete_table("old_table")
```

#### 数据库客户端

```python
from blazestore import read_ck, read_mysql, write_mysql, download_ck

# 从 ClickHouse 读取
df = read_ck("SELECT * FROM trades WHERE date = '2024-01-01'")

# 从 MySQL 读取
df = read_mysql("SELECT * FROM users WHERE id = 1")

# 写入 MySQL
write_mysql(df, "users")

# ClickHouse 批量下载到文件（使用 clickhouse-client）
download_ck("SELECT * FROM big_table", "output.parquet")
```

配置示例（`~/.blaze/config.toml`）：

```toml
[paths]
store = "/home/user/BlazeStore"

[databases.ck]
urls = ["192.168.1.100:9000"]
user = "default"
password = ""

[databases.mysql]
url = "127.0.0.1:3306"
user = "root"
password = ""
```

---

### ygo — 并发任务框架

基于 joblib 的并行调度，支持任务分组、进度条。

```python
from ygo import Pool

pool = Pool(n_jobs=4, show_progress=True)

# 方式一：装饰器注册（推荐）
@pool.submit(job_name="download")
def download(date: str) -> dict:
    return {"date": date, "data": fetch_data(date)}

# 调用注册函数会将任务加入池中
download(date="2024-01-01")
download(date="2024-01-02")

# 并行执行所有任务
results = pool.do()  # -> [{"date": "2024-01-01", ...}, {"date": "2024-01-02", ...}]

# 方式二：延迟函数（适用于批量生成）
from ygo import delay

jobs = [delay(fetch_data).bind(day=d) for d in trading_days]
pool.submit_batch(jobs, job_name="batch_download")
pool.do()
```

Pool 支持上下文管理器：

```python
with Pool(n_jobs=8) as pool:
    for day in trading_days:
        pool.submit(download)(date=day)
    results = pool.do()
```

---

### clickhouse_df — ClickHouse 数据库驱动

```python
import clickhouse_df

# 连接（随机负载均衡）
conn = clickhouse_df.connect(
    urls=["192.168.1.100:9000", "192.168.1.101:9000"],
    user="default",
    password="",
)

# 查询为 Polars DataFrame
df = clickhouse_df.to_polars("SELECT * FROM trades LIMIT 10")
# shape: (10, 5)

# 查询为 Pandas DataFrame
pdf = clickhouse_df.to_pandas("SELECT * FROM trades LIMIT 10")

# 关闭当前线程所有连接
clickhouse_df.close_all()

# 命令行批量下载（适合大结果集，直接写入 Parquet）
clickhouse_df.raw_download("SELECT * FROM big_table", "output.parquet", settings)
```

---

## 开发

```bash
uv sync                    # 安装依赖
uv run pytest tests/       # 运行测试
uv run ruff check .        # 代码检查
uv run ruff format .       # 格式化代码
```

## 许可证

[MIT](LICENSE)
