"""MySQL 适配层：把现有 SQLite 风格的 SQL 翻译成 MySQL 能执行的语句。

调用方仍然写 `?` 占位符、`INSERT OR IGNORE`、`ON CONFLICT ... DO UPDATE`，
这里统一转换，避免把 257 条语句逐条改写。
"""
from __future__ import annotations

import re
from urllib.parse import urlparse

import pymysql
from pymysql.cursors import DictCursor

_INSERT_IGNORE = re.compile(r"\bINSERT\s+OR\s+IGNORE\s+INTO\b", re.IGNORECASE)
_INSERT_REPLACE = re.compile(r"\bINSERT\s+OR\s+REPLACE\s+INTO\b", re.IGNORECASE)
_ON_CONFLICT = re.compile(
    r"\bON\s+CONFLICT\s*\([^)]*\)\s*DO\s+UPDATE\s+SET\b", re.IGNORECASE)
_ON_CONFLICT_NOTHING = re.compile(r"\bON\s+CONFLICT\s*\([^)]*\)\s*DO\s+NOTHING\b", re.IGNORECASE)
_EXCLUDED = re.compile(r"\bexcluded\.(\w+)", re.IGNORECASE)
# ? -> %s，但跳过引号内的内容
_PLACEHOLDER = re.compile(r"'(?:[^']|'')*'|(\?)")


def translate(sql: str) -> str:
    sql = _INSERT_IGNORE.sub("INSERT IGNORE INTO", sql)
    sql = _INSERT_REPLACE.sub("REPLACE INTO", sql)
    sql = _ON_CONFLICT.sub("ON DUPLICATE KEY UPDATE", sql)
    sql = _ON_CONFLICT_NOTHING.sub("", sql)
    sql = _EXCLUDED.sub(r"VALUES(\1)", sql)

    def replace(match: re.Match) -> str:
        return match.group(0) if match.group(0) != "?" else "%s"

    return _PLACEHOLDER.sub(replace, sql)


def split_statements(script: str) -> list[str]:
    """按分号切分，忽略字符串里的分号。"""
    statements, current, quote = [], [], False
    for char in script:
        if char == "'":
            quote = not quote
        if char == ";" and not quote:
            statement = "".join(current).strip()
            if statement:
                statements.append(statement)
            current = []
            continue
        current.append(char)
    tail = "".join(current).strip()
    if tail:
        statements.append(tail)
    return statements


LONG_TEXT_COLUMNS = (
    "payload", "snapshot", "text", "note", "description", "title", "url",
    "content", "answer", "question", "summary", "message", "reason",
)


def translate_schema(script: str) -> list[str]:
    """把 SQLite DDL 转成 MySQL 8 / MariaDB 兼容的语句列表。

    SQLite 的 TEXT 既能当主键也能存长文本；MySQL 里主键必须限长，
    所以统一先转 VARCHAR(255)，再把已知的长文本列改回 LONGTEXT。
    """
    script = re.sub(r"^\s*(BEGIN(\s+IMMEDIATE)?|COMMIT)\s*;\s*$", "",
                    script, flags=re.IGNORECASE | re.MULTILINE)
    script = script.replace("INTEGER PRIMARY KEY AUTOINCREMENT", "BIGINT AUTO_INCREMENT PRIMARY KEY")
    script = re.sub(r"\bBLOB\b", "LONGBLOB", script)
    script = re.sub(r"\bTEXT\b", "VARCHAR(255)", script)
    for column in LONG_TEXT_COLUMNS:
        script = re.sub(rf"\b{column}\s+VARCHAR\(255\)", f"{column} LONGTEXT", script)
    script = re.sub(r"\bAUTOINCREMENT\b", "AUTO_INCREMENT", script, flags=re.IGNORECASE)
    # 外键在 MySQL 里受列类型/建表顺序约束，业务逻辑本就不依赖级联，
    # 直接去掉，避免 CREATE TABLE 因 FK 不匹配失败。
    script = re.sub(r"\s+ON\s+DELETE\s+(CASCADE|SET\s+NULL|RESTRICT|NO\s+ACTION)",
                    "", script, flags=re.IGNORECASE)
    script = re.sub(r",?\s*FOREIGN\s+KEY\s*\([^)]*\)\s*REFERENCES\s+\w+\s*\([^)]*\)",
                    "", script, flags=re.IGNORECASE)
    script = re.sub(r"\s*REFERENCES\s+\w+\s*\([^)]*\)", "", script, flags=re.IGNORECASE)

    statements = []
    for statement in split_statements(script):
        statement = statement.strip()
        if not statement:
            continue
        statement = statement.replace("CREATE INDEX IF NOT EXISTS", "CREATE INDEX")
        if re.match(r"CREATE TABLE", statement, re.IGNORECASE) and "ENGINE=" not in statement.upper():
            statement += " ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci"
        statements.append(translate(statement))
    return statements


class Row(dict):
    """同时支持 row["col"] 和 row[0]：SQLite 的 Row 两种都行，业务代码依赖这个行为。"""

    def __getitem__(self, key):
        if isinstance(key, int):
            return list(self.values())[key]
        return super().__getitem__(key)


class Cursor:
    def __init__(self, cursor):
        self._cursor = cursor

    def fetchone(self):
        row = self._cursor.fetchone()
        return Row(row) if row is not None else None

    def fetchall(self):
        return [Row(row) for row in self._cursor.fetchall()]

    def fetchmany(self, size=None):
        rows = self._cursor.fetchmany(size) if size else self._cursor.fetchmany()
        return [Row(row) for row in rows]

    def __iter__(self):
        for row in self._cursor:
            yield Row(row)

    def __getattr__(self, name):
        return getattr(self._cursor, name)


class MysqlConnection:
    """把 pymysql 连接包装成 sqlite3.Connection 的常用子集。"""

    def __init__(self, connection):
        self._connection = connection
        self.row_factory = None

    def execute(self, sql: str, params=()):
        statement = sql.strip()
        if statement.upper() in ("BEGIN", "BEGIN IMMEDIATE"):
            self._connection.begin()
            return _EmptyCursor()
        if statement.upper() == "COMMIT":
            self._connection.commit()
            return _EmptyCursor()
        cursor = self._connection.cursor()
        cursor.execute(translate(sql), tuple(params) if params else None)
        return Cursor(cursor)

    def executemany(self, sql: str, seq):
        cursor = self._connection.cursor()
        cursor.executemany(translate(sql), [tuple(item) for item in seq])
        return Cursor(cursor)

    def executescript(self, script: str):
        for statement in translate_schema(script):
            try:
                with self._connection.cursor() as cursor:
                    cursor.execute(statement)
            except pymysql.err.OperationalError as error:
                # 索引/表已存在时 MySQL 没有 IF NOT EXISTS，忽略重复定义。
                if error.args and error.args[0] in (1050, 1061, 1826):
                    continue
                raise

    def commit(self):
        self._connection.commit()

    def rollback(self):
        self._connection.rollback()

    def close(self):
        self._connection.close()

    def cursor(self):
        return self._connection.cursor()


class _EmptyCursor:
    def fetchone(self):
        return None

    def fetchall(self):
        return []


class _EmptyResult:
    pass


def connect(url: str) -> MysqlConnection:
    parsed = urlparse(url)
    if not parsed.hostname:
        raise RuntimeError("MySQL 连接串格式应为 mysql://user:password@host:port/database")
    connection = pymysql.connect(
        host=parsed.hostname,
        port=parsed.port or 3306,
        user=parsed.username or "root",
        password=parsed.password or "",
        database=parsed.path.lstrip("/") or None,
        charset="utf8mb4",
        cursorclass=DictCursor,
        autocommit=False,
    )
    with connection.cursor() as cursor:
        cursor.execute("SET NAMES utf8mb4 COLLATE utf8mb4_unicode_ci")
    return MysqlConnection(connection)


def database_name(url: str) -> str:
    return (urlparse(url).path or "").lstrip("/")


def server_connect(url: str):
    """连到服务器（不带库），用于 CREATE DATABASE。"""
    parsed = urlparse(url)
    return pymysql.connect(
        host=parsed.hostname, port=parsed.port or 3306,
        user=parsed.username or "root", password=parsed.password or "",
        charset="utf8mb4", cursorclass=DictCursor, autocommit=True)


def ensure_database(url: str) -> None:
    name = database_name(url)
    if not name:
        raise RuntimeError("MySQL 连接串缺少数据库名")
    server = server_connect(url)
    try:
        with server.cursor() as cursor:
            cursor.execute(
                f"CREATE DATABASE IF NOT EXISTS `{name}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci")
    finally:
        server.close()
