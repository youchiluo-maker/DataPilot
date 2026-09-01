from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import random
import re
import sqlite3
from threading import RLock
import time
from typing import Any

import pandas as pd


class SQLSafetyError(ValueError):
    """Raised when a query is not a single read-only SQL statement."""


class QueryExecutionError(RuntimeError):
    """Raised when SQLite cannot execute a validated query."""


@dataclass(frozen=True)
class QueryResult:
    sql: str
    columns: list[str]
    rows: list[tuple[Any, ...]]
    duration_seconds: float


SCHEMA_SQL = """
CREATE TABLE users (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    region TEXT NOT NULL,
    signup_date TEXT NOT NULL
);
CREATE TABLE products (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    category TEXT NOT NULL,
    unit_price REAL NOT NULL
);
CREATE TABLE orders (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL,
    order_date TEXT NOT NULL,
    status TEXT NOT NULL,
    total_amount REAL NOT NULL,
    FOREIGN KEY(user_id) REFERENCES users(id)
);
CREATE TABLE order_items (
    id INTEGER PRIMARY KEY,
    order_id INTEGER NOT NULL,
    product_id INTEGER NOT NULL,
    quantity INTEGER NOT NULL,
    unit_price REAL NOT NULL,
    FOREIGN KEY(order_id) REFERENCES orders(id),
    FOREIGN KEY(product_id) REFERENCES products(id)
);
CREATE TABLE payments (
    id INTEGER PRIMARY KEY,
    order_id INTEGER NOT NULL,
    paid_at TEXT,
    status TEXT NOT NULL,
    amount REAL NOT NULL,
    FOREIGN KEY(order_id) REFERENCES orders(id)
);
CREATE TABLE refunds (
    id INTEGER PRIMARY KEY,
    order_id INTEGER NOT NULL,
    refund_date TEXT NOT NULL,
    amount REAL NOT NULL,
    reason TEXT NOT NULL,
    FOREIGN KEY(order_id) REFERENCES orders(id)
);
""".strip()


TABLE_DESCRIPTIONS = {
    "users": "用户信息：地区、注册日期",
    "products": "商品信息：名称、品类、单价",
    "orders": "订单主表：用户、日期、状态、订单金额",
    "order_items": "订单明细：商品、数量、成交单价",
    "payments": "支付记录：支付时间、状态、金额",
    "refunds": "退款记录：退款日期、金额、原因",
}


def validate_read_only_sql(sql: str) -> str:
    """Validate one SELECT/WITH statement and return a normalized SQL string."""
    if not isinstance(sql, str) or not sql.strip():
        raise SQLSafetyError("SQL 不能为空。")

    without_comments = re.sub(r"--[^\n]*|/\*.*?\*/", "", sql, flags=re.S)
    candidate = without_comments.strip()
    if candidate.endswith(";"):
        candidate = candidate[:-1].rstrip()

    if ";" in candidate:
        raise SQLSafetyError("只允许执行一条 SQL 语句。")
    if not re.match(r"^(SELECT|WITH)\b", candidate, flags=re.I):
        raise SQLSafetyError("只允许执行 SELECT 或 WITH 查询。")

    blocked = re.compile(
        r"\b(ATTACH|ALTER|CREATE|DELETE|DETACH|DROP|INSERT|PRAGMA|REINDEX|REPLACE|TRUNCATE|UPDATE|VACUUM)\b",
        flags=re.I,
    )
    match = blocked.search(candidate)
    if match:
        raise SQLSafetyError(f"检测到禁止的写操作或管理操作：{match.group(1).upper()}。")
    return candidate


class DemoDatabase:
    """Read-only in-memory database for the demo dataset or uploaded tables."""

    def __init__(
        self,
        *,
        seed: int = 7,
        max_rows: int = 500,
        timeout_seconds: float = 2.0,
        dataframes: Mapping[str, pd.DataFrame] | None = None,
        table_descriptions: Mapping[str, str] | None = None,
    ):
        self.max_rows = max_rows
        self.timeout_seconds = timeout_seconds
        self.template_mode = dataframes is None
        self.table_descriptions = dict(TABLE_DESCRIPTIONS)
        self._query_lock = RLock()
        if table_descriptions:
            self.table_descriptions.update(table_descriptions)
        self.connection = sqlite3.connect(":memory:", check_same_thread=False)
        self.connection.execute("PRAGMA foreign_keys = ON")
        if dataframes is None:
            self.connection.executescript(SCHEMA_SQL)
            self._schema_sql = SCHEMA_SQL
            self._allowed_tables = frozenset(TABLE_DESCRIPTIONS)
            self._fallback_table = "orders"
            self._seed(seed)
        else:
            self._load_dataframes(dataframes)

    @property
    def table_names(self) -> list[str]:
        return sorted(self._allowed_tables)

    @property
    def fallback_table(self) -> str:
        return self._fallback_table

    @property
    def schema_text(self) -> str:
        descriptions = "\n".join(
            f"- {table}: {description}"
            for table, description in self.table_descriptions.items()
            if table in self._allowed_tables
        )
        return f"表说明：\n{descriptions}\n\n建表 SQL：\n{self._schema_sql}"

    def _load_dataframes(self, dataframes: Mapping[str, pd.DataFrame]) -> None:
        if not dataframes:
            raise ValueError("至少需要一个非空数据表。")
        statements: list[str] = []
        allowed: set[str] = set()
        for table_name, frame in dataframes.items():
            if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", table_name):
                raise ValueError(f"表名不安全：{table_name}")
            if table_name in allowed:
                raise ValueError(f"表名重复：{table_name}")
            if frame.empty:
                raise ValueError(f"数据表为空：{table_name}")
            columns = [str(column) for column in frame.columns]
            if not columns or len(set(columns)) != len(columns):
                raise ValueError(f"数据表列名为空或重复：{table_name}")
            if any(not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", column) for column in columns):
                raise ValueError(f"数据表包含未规范化列名：{table_name}")
            definitions = ", ".join(
                f'"{column}" {self._sqlite_type(frame[column])}'
                for column in columns
            )
            statement = f'CREATE TABLE "{table_name}" ({definitions});'
            self.connection.execute(statement)
            frame.loc[:, columns].to_sql(
                table_name, self.connection, if_exists="append", index=False
            )
            statements.append(statement)
            allowed.add(table_name)
        self.connection.commit()
        self._allowed_tables = frozenset(allowed)
        self._fallback_table = sorted(allowed)[0]
        self._schema_sql = "\n".join(statements)

    @staticmethod
    def _sqlite_type(series: pd.Series) -> str:
        if pd.api.types.is_bool_dtype(series) or pd.api.types.is_integer_dtype(series):
            return "INTEGER"
        if pd.api.types.is_float_dtype(series):
            return "REAL"
        return "TEXT"

    def _seed(self, seed: int) -> None:
        rng = random.Random(seed)
        regions = ["华东", "华南", "华北", "西南"]
        users = [
            (index, f"用户{index:03d}", regions[(index - 1) % len(regions)], f"2024-{(index % 12) + 1:02d}-15")
            for index in range(1, 31)
        ]
        products = [
            (1, "机械键盘", "外设", 299.0),
            (2, "无线鼠标", "外设", 159.0),
            (3, "27英寸显示器", "显示设备", 1499.0),
            (4, "USB-C 扩展坞", "配件", 249.0),
            (5, "降噪耳机", "音频", 799.0),
            (6, "智能音箱", "音频", 399.0),
            (7, "移动硬盘", "存储", 599.0),
            (8, "桌面麦克风", "音频", 499.0),
            (9, "人体工学椅", "办公", 1299.0),
            (10, "升降桌", "办公", 1899.0),
            (11, "摄像头", "配件", 329.0),
            (12, "阅读灯", "办公", 179.0),
        ]
        self.connection.executemany("INSERT INTO users VALUES (?, ?, ?, ?)", users)
        self.connection.executemany("INSERT INTO products VALUES (?, ?, ?, ?)", products)

        orders: list[tuple[Any, ...]] = []
        order_items: list[tuple[Any, ...]] = []
        payments: list[tuple[Any, ...]] = []
        refunds: list[tuple[Any, ...]] = []
        statuses = ["paid", "paid", "shipped", "completed", "pending", "cancelled"]
        refund_reasons = ["质量问题", "物流延迟", "重复下单", "用户改变主意"]
        item_id = 1
        payment_id = 1
        refund_id = 1

        for order_id in range(1, 181):
            month = ((order_id - 1) % 12) + 1
            day = ((order_id * 7) % 26) + 1
            order_date = f"2025-{month:02d}-{day:02d}"
            user_id = rng.randint(1, len(users))
            status = rng.choice(statuses)
            product_id = rng.randint(1, len(products))
            quantity = rng.randint(1, 3)
            unit_price = products[product_id - 1][3]
            total = round(quantity * unit_price * rng.choice([0.95, 1.0, 1.0, 1.05]), 2)
            orders.append((order_id, user_id, order_date, status, total))
            order_items.append((item_id, order_id, product_id, quantity, unit_price))
            item_id += 1

            if status != "pending":
                payment_status = "succeeded" if status != "cancelled" else "refunded"
                payments.append((payment_id, order_id, order_date, payment_status, total))
                payment_id += 1

            if status in {"shipped", "completed"} and order_id % 9 == 0:
                refund_amount = round(total * rng.choice([0.5, 1.0]), 2)
                refunds.append(
                    (refund_id, order_id, order_date, refund_amount, rng.choice(refund_reasons))
                )
                refund_id += 1

        self.connection.executemany("INSERT INTO orders VALUES (?, ?, ?, ?, ?)", orders)
        self.connection.executemany("INSERT INTO order_items VALUES (?, ?, ?, ?, ?)", order_items)
        self.connection.executemany("INSERT INTO payments VALUES (?, ?, ?, ?, ?)", payments)
        self.connection.executemany("INSERT INTO refunds VALUES (?, ?, ?, ?, ?)", refunds)
        self.connection.commit()

    def _install_read_only_authorizer(self) -> None:
        denied_actions = {
            sqlite3.SQLITE_INSERT,
            sqlite3.SQLITE_UPDATE,
            sqlite3.SQLITE_DELETE,
            sqlite3.SQLITE_ALTER_TABLE,
            sqlite3.SQLITE_CREATE_INDEX,
            sqlite3.SQLITE_CREATE_TABLE,
            sqlite3.SQLITE_CREATE_TEMP_INDEX,
            sqlite3.SQLITE_CREATE_TEMP_TABLE,
            sqlite3.SQLITE_CREATE_TEMP_TRIGGER,
            sqlite3.SQLITE_CREATE_TEMP_VIEW,
            sqlite3.SQLITE_CREATE_TRIGGER,
            sqlite3.SQLITE_CREATE_VIEW,
            sqlite3.SQLITE_DROP_INDEX,
            sqlite3.SQLITE_DROP_TABLE,
            sqlite3.SQLITE_DROP_TEMP_INDEX,
            sqlite3.SQLITE_DROP_TEMP_TABLE,
            sqlite3.SQLITE_DROP_TEMP_TRIGGER,
            sqlite3.SQLITE_DROP_TEMP_VIEW,
            sqlite3.SQLITE_DROP_TRIGGER,
            sqlite3.SQLITE_DROP_VIEW,
            sqlite3.SQLITE_ATTACH,
            sqlite3.SQLITE_DETACH,
            sqlite3.SQLITE_PRAGMA,
        }

        allowed_tables = self._allowed_tables

        def authorizer(
            action: int,
            arg1: str | None,
            _arg2: str | None,
            _db: str,
            _source: str,
        ) -> int:
            if action in denied_actions:
                return sqlite3.SQLITE_DENY
            if action == sqlite3.SQLITE_READ and arg1 and arg1.lower() not in allowed_tables:
                return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK

        self.connection.set_authorizer(authorizer)

    def execute_read_only(self, sql: str) -> QueryResult:
        with self._query_lock:
            return self._execute_read_only_locked(sql)

    def _execute_read_only_locked(self, sql: str) -> QueryResult:
        safe_sql = validate_read_only_sql(sql)
        executed_sql = safe_sql
        if not re.search(r"\bLIMIT\b", safe_sql, flags=re.I):
            executed_sql = f"{safe_sql}\nLIMIT {self.max_rows}"

        started = time.perf_counter()
        deadline = started + self.timeout_seconds

        def progress_handler() -> int:
            return 1 if time.perf_counter() >= deadline else 0

        self._install_read_only_authorizer()
        self.connection.set_progress_handler(progress_handler, 1000)
        try:
            cursor = self.connection.execute(executed_sql)
            rows = cursor.fetchmany(self.max_rows)
            return QueryResult(
                sql=executed_sql,
                columns=[column[0] for column in cursor.description or []],
                rows=rows,
                duration_seconds=time.perf_counter() - started,
            )
        except SQLSafetyError:
            raise
        except sqlite3.Error as exc:
            raise QueryExecutionError(str(exc)) from exc
        finally:
            self.connection.set_progress_handler(None, 0)
            self.connection.set_authorizer(None)

    def close(self) -> None:
        self.connection.close()
