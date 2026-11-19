"""Database access layer.

PostgreSQL is the production database (Docker Compose). SQLite is supported only so the
API can be exercised without Docker during development; `sqlite_statements` performs a
small, documented translation of the PostgreSQL schema for that purpose.
"""
import re
import sqlite3
from datetime import datetime, timezone

from flask import current_app, g

from .errors import ApiError

try:
    import psycopg2
    import psycopg2.extras
except ImportError:  # SQLite-only local runs do not need the driver
    psycopg2 = None

INTEGRITY_ERRORS = (sqlite3.IntegrityError,) + ((psycopg2.IntegrityError,) if psycopg2 else ())


def now_iso():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def to_iso(value):
    """Normalise database timestamps (datetime from PostgreSQL, text from SQLite) to UTC ISO-8601."""
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).replace(microsecond=0).isoformat()
    return str(value)


class Tx:
    """Thin wrapper giving one API over psycopg2 (%s placeholders) and sqlite3 (? placeholders)."""

    def __init__(self, conn, sqlite):
        self.conn = conn
        self.sqlite = sqlite

    def _prepare(self, sql):
        return sql.replace("%s", "?") if self.sqlite else sql

    def _execute(self, sql, params):
        if self.sqlite:
            cur = self.conn.cursor()
        else:
            cur = self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(self._prepare(sql), tuple(params))
        return cur

    def one(self, sql, params=(), lock=False):
        if lock and not self.sqlite:
            sql = sql.rstrip() + " FOR UPDATE"  # row lock: serialises concurrent writers on this row
        row = self._execute(sql, params).fetchone()
        return dict(row) if row is not None else None

    def all(self, sql, params=()):
        return [dict(r) for r in self._execute(sql, params).fetchall()]

    def execute(self, sql, params=()):
        return self._execute(sql, params).rowcount

    def insert(self, sql, params=()):
        cur = self._execute(sql.rstrip().rstrip(";") + " RETURNING id", params)
        return dict(cur.fetchone())["id"]

    def begin(self):
        if self.sqlite:
            self.conn.execute("BEGIN IMMEDIATE")  # SQLite: take the write lock up front
        # psycopg2 opens a transaction implicitly on the first statement

    def commit(self):
        if self.sqlite:
            self.conn.execute("COMMIT")
        else:
            self.conn.commit()

    def rollback(self):
        if self.sqlite:
            if self.conn.in_transaction:
                self.conn.execute("ROLLBACK")
        else:
            self.conn.rollback()


def connect(url):
    if url.startswith("sqlite:///"):
        conn = sqlite3.connect(url[len("sqlite:///"):], timeout=30, isolation_level=None, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return Tx(conn, sqlite=True)
    if psycopg2 is None:
        raise RuntimeError("psycopg2 is required to use PostgreSQL")
    return Tx(psycopg2.connect(url), sqlite=False)


def get_tx():
    if "tx" not in g:
        g.tx = connect(current_app.config["DATABASE_URL"])
    return g.tx


def close_tx(_exc=None):
    tx = g.pop("tx", None)
    if tx is not None:
        try:
            tx.rollback()  # discards anything not committed by the request
        finally:
            tx.conn.close()


def translate_integrity(exc):
    text = str(exc)
    if "bookings_no_overlap" in text:
        return ApiError(409, "BOOKING_OVERLAP", "The facility is already reserved for an overlapping time")
    if "UNIQUE" in text.upper() or "duplicate key" in text.lower():
        return ApiError(409, "CONFLICT", "A record with the same unique value already exists")
    return ApiError(409, "CONFLICT", "The request conflicts with existing data")


def write(fn):
    """Run fn(tx) inside one transaction. Commit on success, roll back on any failure."""
    tx = get_tx()
    tx.begin()
    try:
        result = fn(tx)
        tx.commit()
        return result
    except INTEGRITY_ERRORS as exc:
        tx.rollback()
        raise translate_integrity(exc) from exc
    except Exception:
        tx.rollback()
        raise


def sqlite_statements(sql):
    """Translate the PostgreSQL schema/seed script into statements SQLite accepts (local testing only)."""
    statements = []
    for raw in sql.split(";"):
        lines = [line for line in raw.splitlines() if not line.strip().startswith("--")]
        stmt = "\n".join(lines).strip()
        if not stmt:
            continue
        upper = stmt.upper()
        if upper.startswith("CREATE EXTENSION") or "EXCLUDE USING" in upper:
            continue  # SQLite has no exclusion constraints; the app-level check still applies
        stmt = stmt.replace("BIGSERIAL PRIMARY KEY", "INTEGER PRIMARY KEY AUTOINCREMENT")
        stmt = re.sub(r"\bTIMESTAMPTZ\b", "TEXT", stmt)
        stmt = re.sub(r"\bJSONB\b", "TEXT", stmt)
        stmt = re.sub(r"\bBIGINT\b", "INTEGER", stmt)
        stmt = re.sub(r"\bNUMERIC\(\d+,\s*\d+\)", "REAL", stmt)
        stmt = re.sub(r"\bBOOLEAN\b", "INTEGER", stmt)
        stmt = re.sub(r"\bCHAR\(64\)", "TEXT", stmt)
        stmt = re.sub(r"\bnow\(\)", "CURRENT_TIMESTAMP", stmt)
        statements.append(stmt)
    return statements
