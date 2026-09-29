import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_ROOT / "estado" / "kontaktu.sqlite3"

SCHEMA = """
CREATE TABLE IF NOT EXISTS leads (
    contact_id TEXT PRIMARY KEY,
    dnc INTEGER NOT NULL DEFAULT 0,
    dnc_reason TEXT,
    whatsapp_blocked INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS call_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    contact_id TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    label TEXT NOT NULL,
    detail_json TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_call_history_contact ON call_history(contact_id);

CREATE TABLE IF NOT EXISTS processed_events (
    idempotency_key TEXT PRIMARY KEY,
    event_id TEXT NOT NULL,
    label TEXT NOT NULL,
    orders_json TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS reminders (
    reminder_id TEXT PRIMARY KEY,
    contact_id TEXT NOT NULL,
    channel TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending'
);
CREATE INDEX IF NOT EXISTS idx_reminders_contact ON reminders(contact_id, status);
"""


@contextmanager
def open_connection():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    connection.executescript(SCHEMA)
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def is_on_dnc(connection, contact_id):
    row = connection.execute(
        "SELECT dnc FROM leads WHERE contact_id = ?", (contact_id,)
    ).fetchone()
    return bool(row and row["dnc"])


def is_whatsapp_blocked(connection, contact_id):
    row = connection.execute(
        "SELECT whatsapp_blocked FROM leads WHERE contact_id = ?", (contact_id,)
    ).fetchone()
    return bool(row and row["whatsapp_blocked"])


def flag_do_not_contact(connection, contact_id, reason):
    connection.execute(
        """
        INSERT INTO leads (contact_id, dnc, dnc_reason)
        VALUES (?, 1, ?)
        ON CONFLICT(contact_id) DO UPDATE SET dnc = 1, dnc_reason = excluded.dnc_reason
        """,
        (contact_id, reason),
    )


def block_whatsapp(connection, contact_id):
    connection.execute(
        """
        INSERT INTO leads (contact_id, whatsapp_blocked)
        VALUES (?, 1)
        ON CONFLICT(contact_id) DO UPDATE SET whatsapp_blocked = 1
        """,
        (contact_id,),
    )


def count_attempts(connection, contact_id):
    row = connection.execute(
        "SELECT COUNT(*) AS n FROM call_history WHERE contact_id = ?",
        (contact_id,),
    ).fetchone()
    return row["n"]


def last_attempt_at(connection, contact_id):
    row = connection.execute(
        """
        SELECT occurred_at FROM call_history
        WHERE contact_id = ? ORDER BY occurred_at DESC LIMIT 1
        """,
        (contact_id,),
    ).fetchone()
    return row["occurred_at"] if row else None


def count_dropped_calls(connection, contact_id):
    row = connection.execute(
        """
        SELECT COUNT(*) AS n FROM call_history
        WHERE contact_id = ? AND label IN ('cortada', 'visita_sin_confirmar')
        """,
        (contact_id,),
    ).fetchone()
    return row["n"]


def record_call(connection, contact_id, idempotency_key, occurred_at, label, detail):
    connection.execute(
        """
        INSERT INTO call_history (contact_id, idempotency_key, occurred_at, label, detail_json)
        VALUES (?, ?, ?, ?, ?)
        """,
        (contact_id, idempotency_key, occurred_at, label, json.dumps(detail, ensure_ascii=False)),
    )


def find_processed_event(connection, idempotency_key):
    row = connection.execute(
        "SELECT * FROM processed_events WHERE idempotency_key = ?",
        (idempotency_key,),
    ).fetchone()
    if row is None:
        return None
    return {
        "idempotency_key": row["idempotency_key"],
        "event_id": row["event_id"],
        "label": row["label"],
        "orders": json.loads(row["orders_json"]),
    }


def record_processed_event(connection, idempotency_key, event_id, label, orders):
    connection.execute(
        """
        INSERT INTO processed_events (idempotency_key, event_id, label, orders_json)
        VALUES (?, ?, ?, ?)
        """,
        (idempotency_key, event_id, label, json.dumps(orders, ensure_ascii=False)),
    )


def pending_reminders(connection, contact_id):
    rows = connection.execute(
        """
        SELECT reminder_id, channel FROM reminders
        WHERE contact_id = ? AND status = 'pending'
        """,
        (contact_id,),
    ).fetchall()
    return [{"reminder_id": r["reminder_id"], "channel": r["channel"]} for r in rows]


def create_reminder(connection, reminder_id, contact_id, channel):
    connection.execute(
        "INSERT INTO reminders (reminder_id, contact_id, channel) VALUES (?, ?, ?)",
        (reminder_id, contact_id, channel),
    )


def cancel_reminder(connection, reminder_id):
    connection.execute(
        "UPDATE reminders SET status = 'cancelled' WHERE reminder_id = ?",
        (reminder_id,),
    )
