import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional

SCHEMA = """
CREATE TABLE IF NOT EXISTS orders (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker TEXT NOT NULL,
    side TEXT NOT NULL,
    quantity INTEGER NOT NULL,
    allocation_pct REAL NOT NULL,
    confidence INTEGER NOT NULL,
    status TEXT NOT NULL,
    reasons TEXT,
    ibkr_order_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""

PENDING = "pending"
CONFIRMED = "confirmed"
REJECTED = "rejected"
SUBMITTED = "submitted"  # sent to the broker but not confirmed filled yet
EXECUTED = "executed"    # confirmed filled by the broker
EXPIRED = "expired"
EXECUTION_FAILED = "execution_failed"
STUCK = "stuck_needs_review"  # process died between CONFIRMED and placing the order


def status_for_fill(broker_status: str) -> str:
    """Maps a broker order status to our EXECUTED/SUBMITTED distinction.

    Only a broker-confirmed "Filled" counts as EXECUTED; anything else
    (Submitted, PreSubmitted, a timed-out wait, ...) is recorded as SUBMITTED
    so the daily trade count and the user's own records never claim a fill
    that hasn't actually happened.
    """
    return EXECUTED if broker_status == "Filled" else SUBMITTED


@dataclass
class Order:
    id: int
    ticker: str
    side: str
    quantity: int
    allocation_pct: float
    confidence: int
    status: str
    reasons: str
    ibkr_order_id: Optional[str]
    created_at: str
    updated_at: str


class OrderStore:
    def __init__(self, db_path: str):
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.db_path = db_path
        with self._connect() as conn:
            conn.execute(SCHEMA)

    @contextmanager
    def _connect(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def create_pending(
        self, ticker: str, side: str, quantity: int, allocation_pct: float,
        confidence: int, reasons: str = "",
    ) -> Order:
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            cursor = conn.execute(
                "INSERT INTO orders (ticker, side, quantity, allocation_pct, confidence, "
                "status, reasons, ibkr_order_id, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, NULL, ?, ?)",
                (ticker, side, quantity, allocation_pct, confidence, PENDING, reasons, now, now),
            )
            order_id = cursor.lastrowid
        return self.get(order_id)

    def get(self, order_id: int) -> Optional[Order]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
            return Order(**dict(row)) if row else None

    def list_pending(self) -> List[Order]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM orders WHERE status = ? ORDER BY created_at", (PENDING,)
            ).fetchall()
            return [Order(**dict(r)) for r in rows]

    def update_status(self, order_id: int, status: str, ibkr_order_id: Optional[str] = None) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self._connect() as conn:
            conn.execute(
                "UPDATE orders SET status = ?, ibkr_order_id = COALESCE(?, ibkr_order_id), "
                "updated_at = ? WHERE id = ?",
                (status, ibkr_order_id, now, order_id),
            )

    def expire_stale(self, ttl_minutes: int) -> int:
        cutoff = (datetime.now(timezone.utc) - timedelta(minutes=ttl_minutes)).isoformat()
        with self._connect() as conn:
            cursor = conn.execute(
                "UPDATE orders SET status = ?, updated_at = ? "
                "WHERE status = ? AND created_at < ?",
                (EXPIRED, datetime.now(timezone.utc).isoformat(), PENDING, cutoff),
            )
            return cursor.rowcount

    def flag_stuck_confirmed(self, ttl_minutes: int) -> List[Order]:
        """Finds CONFIRMED orders that never transitioned to SUBMITTED/EXECUTED/
        EXECUTION_FAILED within ttl_minutes - almost always because the process
        died between marking CONFIRMED and calling the broker - and marks them
        STUCK. Never auto-retried: we can't tell whether the broker already
        received the order, so a blind retry could double-place it. Surfacing
        it for a human to check is the safe default.
        """
        cutoff = (datetime.now(timezone.utc) - timedelta(minutes=ttl_minutes)).isoformat()
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM orders WHERE status = ? AND updated_at < ?",
                (CONFIRMED, cutoff),
            ).fetchall()
            stuck = [Order(**dict(r)) for r in rows]
            if stuck:
                now = datetime.now(timezone.utc).isoformat()
                conn.executemany(
                    "UPDATE orders SET status = ?, updated_at = ? WHERE id = ?",
                    [(STUCK, now, o.id) for o in stuck],
                )
            return stuck

    def count_executed_today(self) -> int:
        """Counts orders whose most recent transition to EXECUTED happened today.

        Filters on updated_at (the execution timestamp), not created_at (when
        the order was first proposed) - an order proposed late one day and
        executed after midnight must count toward the new day's limit, not
        the day it was merely proposed.
        """
        today = datetime.now(timezone.utc).date().isoformat()
        with self._connect() as conn:
            row = conn.execute(
                "SELECT COUNT(*) as n FROM orders WHERE status = ? AND updated_at >= ?",
                (EXECUTED, today),
            ).fetchone()
            return row["n"]
