"""SQLite state store for Dental Voice AI Agent.

Stores transient per-call state (appointment selections, slot data) in SQLite
so global_data stays lightweight (~1KB). Also caches provider/operatory lookups.
"""

import json
import logging
import sqlite3
import time
from pathlib import Path

logger = logging.getLogger(__name__)

DB_PATH = Path(__file__).parent / "dental_state.db"

_CREATE_TABLES = """
CREATE TABLE IF NOT EXISTS call_state (
    call_id    TEXT PRIMARY KEY,
    state_json TEXT NOT NULL DEFAULT '{}',
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS call_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    call_id     TEXT NOT NULL,
    pat_num     INTEGER,
    patient_name TEXT,
    phone       TEXT,
    intent      TEXT,
    outcome     TEXT,
    apt_num     INTEGER,
    summary     TEXT,
    created_at  TEXT NOT NULL DEFAULT (datetime('now'))
);
"""

DEFAULT_STATE = {
    "intent": None,              # book, confirm, reschedule, cancel
    "pat_num": None,
    "selected_apt_num": None,    # for confirm/reschedule/cancel flows
    "available_slots": None,     # full slot data from API
    "slot_summaries": None,      # voice-friendly slot strings
    "selected_slot": None,       # the slot the caller picked
    "appointment_prefs": None,   # reason, date, time pref, provider pref
    "booked_appointment": None,  # result of booking
}


def _connect():
    """Open a new connection with WAL mode."""
    conn = sqlite3.connect(str(DB_PATH), timeout=5)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(_CREATE_TABLES)
    return conn


def load_call_state(call_id):
    """Return the full state dict for a call, or defaults if missing."""
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT state_json FROM call_state WHERE call_id = ?", (call_id,)
        ).fetchone()
        if row:
            state = json.loads(row[0])
            merged = {**DEFAULT_STATE, **state}
            return merged
        return dict(DEFAULT_STATE)
    finally:
        conn.close()


def save_call_state(call_id, state):
    """Upsert the JSON blob for a call."""
    now = time.time()
    blob = json.dumps(state, default=str)
    conn = _connect()
    try:
        conn.execute(
            """INSERT INTO call_state (call_id, state_json, created_at, updated_at)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(call_id) DO UPDATE SET
                   state_json = excluded.state_json,
                   updated_at = excluded.updated_at""",
            (call_id, blob, now, now),
        )
        conn.commit()
    finally:
        conn.close()


def delete_call_state(call_id):
    """Remove a call's state after the call ends."""
    conn = _connect()
    try:
        conn.execute("DELETE FROM call_state WHERE call_id = ?", (call_id,))
        conn.commit()
        logger.info(f"Deleted state for call_id={call_id}")
    finally:
        conn.close()


def cleanup_stale_states(max_age_hours=24):
    """Prune abandoned calls older than max_age_hours."""
    cutoff = time.time() - (max_age_hours * 3600)
    conn = _connect()
    try:
        cursor = conn.execute(
            "DELETE FROM call_state WHERE updated_at < ?", (cutoff,)
        )
        conn.commit()
        if cursor.rowcount:
            logger.info(f"Cleaned up {cursor.rowcount} stale call states")
    finally:
        conn.close()


def build_ai_summary(state):
    """Extract a lightweight dict for global_data.

    Only includes what the AI needs to conduct the conversation.
    Heavy objects (full slot arrays) stay in SQLite only.
    """
    summary = {}

    if state.get("intent"):
        summary["intent"] = state["intent"]
    if state.get("pat_num"):
        summary["pat_num"] = state["pat_num"]
    if state.get("selected_apt_num"):
        summary["selected_apt_num"] = state["selected_apt_num"]

    # Slot summaries — AI reads these to the caller (text only)
    if state.get("slot_summaries"):
        summary["slot_summaries"] = state["slot_summaries"]

    # Selected slot — what the caller picked
    if state.get("selected_slot"):
        summary["selected_slot"] = state["selected_slot"]

    # Booked appointment details
    if state.get("booked_appointment"):
        summary["booked_appointment"] = state["booked_appointment"]

    # Appointment preferences from gather
    if state.get("appointment_prefs"):
        summary["appointment_prefs"] = state["appointment_prefs"]

    # Flags
    summary["has_slots"] = bool(state.get("available_slots"))
    summary["has_selected_slot"] = state.get("selected_slot") is not None
    summary["has_booked"] = state.get("booked_appointment") is not None

    return summary


def save_call_log(call_id, pat_num=None, patient_name=None, phone=None,
                  intent=None, outcome=None, apt_num=None, summary=None):
    """Insert a call log entry for the dashboard."""
    conn = _connect()
    try:
        conn.execute(
            """INSERT INTO call_log
               (call_id, pat_num, patient_name, phone, intent, outcome,
                apt_num, summary)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (call_id, pat_num, patient_name, phone, intent, outcome,
             apt_num, summary),
        )
        conn.commit()
        logger.info(f"Saved call log for call_id={call_id}")
    finally:
        conn.close()


def get_all_call_logs():
    """Return all call logs ordered by most recent first."""
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT * FROM call_log ORDER BY created_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()
