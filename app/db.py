"""SQLite helpers for MagicLink."""
from __future__ import annotations

import datetime
import os
import sqlite3
from pathlib import Path
from typing import Iterator

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = Path(os.environ.get("MAGICLINK_DB", BASE_DIR / "magiclink.db"))
SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"


def utcnow() -> str:
    """Current UTC time as an ISO-8601 string (seconds precision)."""
    return datetime.datetime.now(datetime.timezone.utc).replace(
        microsecond=0).isoformat()


def connect() -> sqlite3.Connection:
    """每个请求一个独立连接。

    check_same_thread=False：FastAPI 把同步端点跑在线程池里，依赖函数和端点函数
    可能落在不同线程上（这正是 500 的来源）。连接是每请求新建、请求内独占使用，
    不存在两个线程同时用同一条连接的情况，所以关掉这个检查是安全的。
    """
    conn = sqlite3.connect(DB_PATH, timeout=10, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def get_db() -> Iterator[sqlite3.Connection]:
    """FastAPI dependency: one connection per request."""
    conn = connect()
    try:
        yield conn
    finally:
        conn.close()


def init_db() -> None:
    conn = connect()
    try:
        # WAL 是写进数据库文件的持久设置，这里设一次即可（并发读更稳）
        conn.execute("PRAGMA journal_mode = WAL")
        # 顺序很重要：必须先把老库缺的列补上，再执行 schema.sql。
        # schema.sql 里给 teams.public_slug 建了索引，老库没有这一列时
        # executescript 会直接抛 "no such column"，整个启动就挂了。
        _migrate(conn)
        with open(SCHEMA_PATH, "r", encoding="utf-8") as f:
            conn.executescript(f.read())
        conn.commit()
    finally:
        conn.close()


# 已有的库补新列。ALTER TABLE ADD COLUMN 不能带 UNIQUE，所以唯一约束走 schema.sql 里的
# 部分索引（CREATE ... IF NOT EXISTS 每次都会执行，老库同样生效）。
_MIGRATIONS = [
    ("users", "public_enabled", "INTEGER NOT NULL DEFAULT 0"),
    ("users", "gitcode_id", "TEXT"),
    ("users", "public_slug", "TEXT"),
    ("teams", "public_enabled", "INTEGER NOT NULL DEFAULT 0"),
    ("teams", "public_slug", "TEXT"),
    ("links", "public_show", "INTEGER NOT NULL DEFAULT 0"),
    # 拖拽排序：组内顺序
    ("links", "position", "INTEGER NOT NULL DEFAULT 0"),
    ("link_team_links", "position", "INTEGER NOT NULL DEFAULT 0"),
]


def _migrate(conn: sqlite3.Connection) -> None:
    """幂等补列：表/列名都来自上面的常量表，不含外部输入。"""
    for table, column, decl in _MIGRATIONS:
        cols = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
        if cols and column not in cols:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {decl}")

