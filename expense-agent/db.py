"""SQLite access layer. SQL only — no AI, no validation of model input."""
import os
import sqlite3
from contextlib import contextmanager
from datetime import date, timedelta

import config  # noqa: F401  (loads .env so EXPENSE_DB can be set there)

DB_PATH = os.environ.get("EXPENSE_DB", "expenses.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS expenses (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    amount   REAL NOT NULL CHECK (amount > 0),
    category TEXT NOT NULL,
    note     TEXT,
    spent_on TEXT NOT NULL
)
"""

LIST_LIMIT = 100  # most rows list_expenses returns to the model

# Columns that update_expense may touch. Column names are never taken from input.
_UPDATABLE = ("amount", "category", "note", "spent_on")


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    with get_conn() as c:
        c.execute(SCHEMA)


def _fetch(conn, expense_id: int):
    row = conn.execute("SELECT * FROM expenses WHERE id = ?", (expense_id,)).fetchone()
    return dict(row) if row else None


def get_expense(expense_id: int):
    with get_conn() as c:
        return _fetch(c, expense_id)


def add_expense(amount: float, category: str, note: str | None = None,
                spent_on: str | None = None) -> dict:
    spent_on = spent_on or date.today().isoformat()
    with get_conn() as c:
        cur = c.execute(
            "INSERT INTO expenses (amount, category, note, spent_on) VALUES (?, ?, ?, ?)",
            (amount, category, note, spent_on),
        )
        return _fetch(c, cur.lastrowid)


def list_expenses(days: int, limit: int = LIST_LIMIT) -> list[dict]:
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    with get_conn() as c:
        rows = c.execute(
            "SELECT * FROM expenses WHERE spent_on >= ? "
            "ORDER BY spent_on DESC, id DESC LIMIT ?",
            (cutoff, limit),
        ).fetchall()
        return [dict(r) for r in rows]


def sum_by_category(days: int) -> list[dict]:
    cutoff = (date.today() - timedelta(days=days)).isoformat()
    with get_conn() as c:
        rows = c.execute(
            "SELECT category, ROUND(SUM(amount), 2) AS total, COUNT(*) AS count "
            "FROM expenses WHERE spent_on >= ? "
            "GROUP BY category ORDER BY total DESC",
            (cutoff,),
        ).fetchall()
        return [dict(r) for r in rows]


def update_expense(expense_id: int, fields: dict):
    cols = [k for k in _UPDATABLE if k in fields]
    if not cols:
        return get_expense(expense_id)
    assignments = ", ".join(f"{k} = ?" for k in cols)  # k comes from the whitelist above
    values = [fields[k] for k in cols] + [expense_id]
    with get_conn() as c:
        cur = c.execute(f"UPDATE expenses SET {assignments} WHERE id = ?", values)
        if cur.rowcount == 0:
            return None
        return _fetch(c, expense_id)


def delete_expense(expense_id: int) -> bool:
    with get_conn() as c:
        cur = c.execute("DELETE FROM expenses WHERE id = ?", (expense_id,))
        return cur.rowcount > 0
