import sqlite3
import threading
from contextlib import contextmanager
import os
from pathlib import Path
from typing import Any, Iterable

from ..core.logger import create_logger

log = create_logger("database")

_BACKEND_ROOT = Path(__file__).resolve().parents[2]
_RAW_DB_PATH = Path(os.environ.get("DATABASE_PATH") or "data/sistem1_v4.db")
DB_PATH = (_RAW_DB_PATH if _RAW_DB_PATH.is_absolute() else _BACKEND_ROOT / _RAW_DB_PATH).resolve()

_db: sqlite3.Connection | None = None
_write_lock = threading.RLock()


def init_db() -> sqlite3.Connection:
    global _db
    if _db is not None:
        return _db
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")
    conn.execute("PRAGMA busy_timeout = 15000")
    conn.execute("PRAGMA temp_store = MEMORY")
    conn.execute("PRAGMA foreign_keys = ON")
    _db = conn
    log.info("Database connected", {"path": str(DB_PATH)})
    return _db


def get_db() -> sqlite3.Connection:
    return _db if _db is not None else init_db()


def close_db() -> None:
    global _db
    if _db is None:
        return
    try:
        _db.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    except Exception as err:  # noqa: BLE001
        log.warn(f"Database checkpoint before close failed: {err}")
    _db.close()
    _db = None


def query_one(sql: str, params: Iterable[Any] = ()) -> sqlite3.Row | None:
    # Tek paylasilan baglanti: okumalar da _write_lock altinda olmali, yoksa acik bir
    # transaction()'in ortasinda calisan SELECT kirli/yarim durum okur (atomiklik kaybi).
    conn = get_db()
    with _write_lock:
        return conn.execute(sql, tuple(params)).fetchone()


def query_all(sql: str, params: Iterable[Any] = ()) -> list[sqlite3.Row]:
    conn = get_db()
    with _write_lock:
        return conn.execute(sql, tuple(params)).fetchall()


def execute(sql: str, params: Iterable[Any] = ()) -> sqlite3.Cursor:
    conn = get_db()
    with _write_lock:
        cur = conn.execute(sql, tuple(params))
        conn.commit()
        return cur


def executemany(sql: str, seq: Iterable[Iterable[Any]]) -> None:
    conn = get_db()
    with _write_lock:
        conn.executemany(sql, [tuple(p) for p in seq])
        conn.commit()


@contextmanager
def transaction():
    conn = get_db()
    with _write_lock:
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
