"""SQLite schema and CRUD for the Seoul APT 59㎡ Index project.

가격 단위 규약:
- DB 저장은 원시값 보존을 위해 hourly_prices.min_price 만 만원 단위 정수 (int).
- hourly_index / hourly_ohlc / daily_ohlc 의 모든 가격은 **억(REAL)** 단위.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime
from typing import Iterable

from config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS complexes (
    complex_no       TEXT PRIMARY KEY,        -- Naver complex_no (canonical)
    complex_name     TEXT NOT NULL,
    district         TEXT NOT NULL,
    household_cnt    INTEGER NOT NULL,
    trade_volume     INTEGER,
    area_no_59       TEXT,
    pyeong_no        TEXT,
    rank             INTEGER,
    selected_at      TIMESTAMP NOT NULL,
    richgo_danji_id  TEXT                     -- Richgo lookup id (nullable)
);

CREATE TABLE IF NOT EXISTS hourly_prices (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    collected_at     TIMESTAMP NOT NULL,
    complex_no       TEXT NOT NULL,
    min_price        INTEGER,           -- 만원, NULL = 매물 없음
    article_count    INTEGER DEFAULT 0,
    FOREIGN KEY (complex_no) REFERENCES complexes(complex_no)
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_hourly_prices_ts_cx
    ON hourly_prices(collected_at, complex_no);
CREATE INDEX IF NOT EXISTS ix_hourly_prices_ts ON hourly_prices(collected_at);

CREATE TABLE IF NOT EXISTS hourly_index (
    collected_at     TIMESTAMP PRIMARY KEY,
    avg_price        REAL,
    median_price     REAL,
    sample_count     INTEGER,
    valid_count      INTEGER
);

CREATE TABLE IF NOT EXISTS hourly_ohlc (
    ts               TIMESTAMP PRIMARY KEY,
    avg_open         REAL,
    avg_high         REAL,
    avg_low          REAL,
    avg_close        REAL,
    median_open      REAL,
    median_high      REAL,
    median_low       REAL,
    median_close     REAL,
    valid_count      INTEGER
);

CREATE TABLE IF NOT EXISTS daily_ohlc (
    date             DATE PRIMARY KEY,
    avg_open         REAL,
    avg_high         REAL,
    avg_low          REAL,
    avg_close        REAL,
    median_open      REAL,
    median_high      REAL,
    median_low       REAL,
    median_close     REAL,
    hour_count       INTEGER
);

CREATE TABLE IF NOT EXISTS meta (
    key              TEXT PRIMARY KEY,
    value            TEXT NOT NULL,
    updated_at       TIMESTAMP NOT NULL
);
"""


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


@contextmanager
def transaction():
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    with transaction() as conn:
        conn.executescript(SCHEMA)
        # Migration: add richgo_danji_id column if missing (existing DB with old schema)
        cols = {r["name"] for r in conn.execute("PRAGMA table_info(complexes)").fetchall()}
        if "richgo_danji_id" not in cols:
            conn.execute("ALTER TABLE complexes ADD COLUMN richgo_danji_id TEXT")


# ── Complexes ──────────────────────────────────────────────────────────────

def upsert_complexes(rows: Iterable[dict], selected_at: datetime) -> None:
    sql = """
    INSERT INTO complexes (
        complex_no, complex_name, district, household_cnt, trade_volume,
        area_no_59, pyeong_no, rank, selected_at, richgo_danji_id
    ) VALUES (
        :complex_no, :complex_name, :district, :household_cnt, :trade_volume,
        :area_no_59, :pyeong_no, :rank, :selected_at, :richgo_danji_id
    )
    ON CONFLICT(complex_no) DO UPDATE SET
        complex_name    = excluded.complex_name,
        district        = excluded.district,
        household_cnt   = excluded.household_cnt,
        trade_volume    = excluded.trade_volume,
        area_no_59      = excluded.area_no_59,
        pyeong_no       = excluded.pyeong_no,
        rank            = excluded.rank,
        selected_at     = excluded.selected_at,
        richgo_danji_id = excluded.richgo_danji_id
    """
    payload = [{
        **r,
        "selected_at": selected_at,
        "richgo_danji_id": r.get("richgo_danji_id"),
    } for r in rows]
    with transaction() as conn:
        conn.executemany(sql, payload)


def get_complexes() -> list[dict]:
    with transaction() as conn:
        rows = conn.execute(
            "SELECT * FROM complexes ORDER BY rank ASC NULLS LAST"
        ).fetchall()
    return [dict(r) for r in rows]


# ── Hourly prices ──────────────────────────────────────────────────────────

def insert_hourly_prices(rows: Iterable[dict]) -> int:
    sql = """
    INSERT OR REPLACE INTO hourly_prices
        (collected_at, complex_no, min_price, article_count)
    VALUES
        (:collected_at, :complex_no, :min_price, :article_count)
    """
    with transaction() as conn:
        cur = conn.executemany(sql, list(rows))
        return cur.rowcount


def get_hourly_prices_at(ts: datetime) -> list[dict]:
    with transaction() as conn:
        rows = conn.execute(
            "SELECT * FROM hourly_prices WHERE collected_at = ?", (ts,)
        ).fetchall()
    return [dict(r) for r in rows]


# ── Hourly index ───────────────────────────────────────────────────────────

def upsert_hourly_index(
    collected_at: datetime,
    avg_price: float | None,
    median_price: float | None,
    sample_count: int,
    valid_count: int,
) -> None:
    with transaction() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO hourly_index
                (collected_at, avg_price, median_price, sample_count, valid_count)
            VALUES (?, ?, ?, ?, ?)
            """,
            (collected_at, avg_price, median_price, sample_count, valid_count),
        )


def get_hourly_index(limit: int = 720) -> list[dict]:
    with transaction() as conn:
        rows = conn.execute(
            "SELECT * FROM hourly_index ORDER BY collected_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
    return [dict(r) for r in reversed(rows)]


# ── OHLC ───────────────────────────────────────────────────────────────────

def upsert_hourly_ohlc(row: dict) -> None:
    sql = """
    INSERT OR REPLACE INTO hourly_ohlc
        (ts, avg_open, avg_high, avg_low, avg_close,
         median_open, median_high, median_low, median_close, valid_count)
    VALUES
        (:ts, :avg_open, :avg_high, :avg_low, :avg_close,
         :median_open, :median_high, :median_low, :median_close, :valid_count)
    """
    with transaction() as conn:
        conn.execute(sql, row)


def upsert_daily_ohlc(row: dict) -> None:
    sql = """
    INSERT OR REPLACE INTO daily_ohlc
        (date, avg_open, avg_high, avg_low, avg_close,
         median_open, median_high, median_low, median_close, hour_count)
    VALUES
        (:date, :avg_open, :avg_high, :avg_low, :avg_close,
         :median_open, :median_high, :median_low, :median_close, :hour_count)
    """
    with transaction() as conn:
        conn.execute(sql, row)


def get_hourly_ohlc(limit: int = 720) -> list[dict]:
    with transaction() as conn:
        rows = conn.execute(
            "SELECT * FROM hourly_ohlc ORDER BY ts DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in reversed(rows)]


def get_daily_ohlc(limit: int = 365) -> list[dict]:
    with transaction() as conn:
        rows = conn.execute(
            "SELECT * FROM daily_ohlc ORDER BY date DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in reversed(rows)]


# ── Meta ───────────────────────────────────────────────────────────────────

def set_meta(key: str, value: str) -> None:
    with transaction() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO meta (key, value, updated_at)
            VALUES (?, ?, ?)
            """,
            (key, value, datetime.utcnow()),
        )


def get_meta(key: str) -> str | None:
    with transaction() as conn:
        row = conn.execute(
            "SELECT value FROM meta WHERE key = ?", (key,)
        ).fetchone()
    return row["value"] if row else None


if __name__ == "__main__":
    init_db()
    print(f"Database initialized at {DB_PATH}")
