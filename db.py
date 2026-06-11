"""FastHelpdesk data layer — SQLite, collapsed from Frappe Helpdesk.

Core entities: customers, agents, teams, tickets, ticket messages (the
conversation), ticket activity (audit), SLA policies, and a knowledge base
(articles + categories). SLA response/resolution targets are derived from the
ticket priority and computed against the clock so the demo shows live "due in"
and "breached" timers.
"""
from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path

DB_PATH = os.getenv("FASTHELPDESK_DB") or str(Path(__file__).parent / "fasthelpdesk.sqlite")

# Ticket statuses, grouped (Frappe categorises Open / Paused / Resolved).
TICKET_STATUSES = ["Open", "Replied", "On Hold", "Resolved", "Closed"]
OPEN_STATUSES = ["Open", "Replied", "On Hold"]
CLOSED_STATUSES = ["Resolved", "Closed"]

PRIORITIES = ["Urgent", "High", "Medium", "Low"]
TICKET_TYPES = ["Question", "Incident", "Bug", "Feature Request", "Unspecified"]
AGENT_AVAILABILITY = ["Available", "Busy", "Away"]
ARTICLE_STATUSES = ["Published", "Draft", "Archived"]

# SLA targets in minutes by priority: (first response, resolution).
SLA_TARGETS = {
    "Urgent": (30, 4 * 60),
    "High": (60, 8 * 60),
    "Medium": (4 * 60, 24 * 60),
    "Low": (8 * 60, 72 * 60),
}


def connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def cursor():
    conn = connect()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def db_exists() -> bool:
    p = Path(DB_PATH)
    return p.exists() and p.stat().st_size > 0


def rows(sql, params=()):
    with cursor() as conn:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]


def one(sql, params=()):
    with cursor() as conn:
        r = conn.execute(sql, params).fetchone()
        return dict(r) if r else None


def scalar(sql, params=()):
    with cursor() as conn:
        r = conn.execute(sql, params).fetchone()
        return r[0] if r else None


SCHEMA = """
CREATE TABLE IF NOT EXISTS agents (
    id            INTEGER PRIMARY KEY,
    name          TEXT NOT NULL,
    email         TEXT UNIQUE,
    team_id       INTEGER REFERENCES teams(id),
    availability  TEXT NOT NULL DEFAULT 'Available',
    is_active     INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS teams (
    id            INTEGER PRIMARY KEY,
    name          TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS customers (
    id            INTEGER PRIMARY KEY,
    name          TEXT NOT NULL,
    domain        TEXT,
    created       TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS contacts (
    id            INTEGER PRIMARY KEY,
    name          TEXT NOT NULL,
    email         TEXT,
    customer_id   INTEGER REFERENCES customers(id)
);
CREATE TABLE IF NOT EXISTS tickets (
    id                  INTEGER PRIMARY KEY,
    subject             TEXT NOT NULL,
    description         TEXT,
    status              TEXT NOT NULL,
    priority            TEXT NOT NULL,
    ticket_type         TEXT,
    customer_id         INTEGER REFERENCES customers(id),
    contact_id          INTEGER REFERENCES contacts(id),
    raised_by           TEXT,
    team_id             INTEGER REFERENCES teams(id),
    agent_id            INTEGER REFERENCES agents(id),
    created             TEXT NOT NULL,
    response_by         TEXT,          -- SLA first-response deadline
    resolution_by       TEXT,          -- SLA resolution deadline
    first_responded_on  TEXT,
    resolved_on         TEXT,
    feedback_rating     INTEGER        -- 1..5, after resolution
);
CREATE TABLE IF NOT EXISTS ticket_messages (
    id            INTEGER PRIMARY KEY,
    ticket_id     INTEGER NOT NULL REFERENCES tickets(id),
    sender        TEXT NOT NULL,       -- 'customer' | 'agent' | 'note'
    author        TEXT,
    body          TEXT NOT NULL,
    created       TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS ticket_activity (
    id            INTEGER PRIMARY KEY,
    ticket_id     INTEGER NOT NULL REFERENCES tickets(id),
    action        TEXT NOT NULL,
    actor         TEXT,
    created       TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS article_categories (
    id            INTEGER PRIMARY KEY,
    name          TEXT NOT NULL,
    icon          TEXT
);
CREATE TABLE IF NOT EXISTS articles (
    id            INTEGER PRIMARY KEY,
    title         TEXT NOT NULL,
    category_id   INTEGER REFERENCES article_categories(id),
    content       TEXT,
    author        TEXT,
    status        TEXT NOT NULL DEFAULT 'Published',
    views         INTEGER NOT NULL DEFAULT 0,
    published_on  TEXT
);
CREATE TABLE IF NOT EXISTS chat_messages (
    id            INTEGER PRIMARY KEY,
    thread_id     TEXT NOT NULL,
    role          TEXT NOT NULL,
    content       TEXT NOT NULL,
    created       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_tickets_status ON tickets(status);
CREATE INDEX IF NOT EXISTS idx_tickets_agent  ON tickets(agent_id);
CREATE INDEX IF NOT EXISTS idx_msg_ticket     ON ticket_messages(ticket_id);
CREATE INDEX IF NOT EXISTS idx_act_ticket     ON ticket_activity(ticket_id);
"""


def init_schema():
    with cursor() as conn:
        conn.executescript(SCHEMA)


# --- SLA helpers ------------------------------------------------------------

def _parse(ts: str | None):
    if not ts:
        return None
    try:
        return datetime.strptime(ts[:19], "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


def sla_state(ticket: dict, now: datetime | None = None) -> dict:
    """Return SLA badge info: {'label','tone','breached'} for a ticket."""
    now = now or datetime(2026, 6, 11, 12, 0, 0)
    if ticket["status"] in CLOSED_STATUSES:
        # judge against resolution deadline vs resolved time
        res_by = _parse(ticket.get("resolution_by"))
        resolved = _parse(ticket.get("resolved_on"))
        if res_by and resolved and resolved > res_by:
            return {"label": "SLA breached", "tone": "breach", "breached": True}
        return {"label": "Within SLA", "tone": "ok", "breached": False}
    # open: which target is live?
    if not ticket.get("first_responded_on"):
        target, kind = _parse(ticket.get("response_by")), "response"
    else:
        target, kind = _parse(ticket.get("resolution_by")), "resolution"
    if not target:
        return {"label": "No SLA", "tone": "neutral", "breached": False}
    delta = target - now
    mins = int(delta.total_seconds() // 60)
    if mins < 0:
        return {"label": f"{kind.title()} overdue {_fmt(-mins)}", "tone": "breach", "breached": True}
    tone = "warn" if mins < 120 else "ok"
    return {"label": f"{kind.title()} due in {_fmt(mins)}", "tone": tone, "breached": False}


def _fmt(mins: int) -> str:
    if mins >= 1440:
        return f"{mins // 1440}d"
    if mins >= 60:
        return f"{mins // 60}h"
    return f"{mins}m"


# --- aggregate reads --------------------------------------------------------

def kpis() -> dict:
    open_q = ",".join("?" * len(OPEN_STATUSES))
    open_tickets = rows(f"SELECT * FROM tickets WHERE status IN ({open_q})", tuple(OPEN_STATUSES))
    breached = sum(1 for t in open_tickets if sla_state(t)["breached"])
    frts = [_parse(t["first_responded_on"]) and
            (_parse(t["first_responded_on"]) - _parse(t["created"])).total_seconds() / 60
            for t in rows("SELECT created, first_responded_on FROM tickets WHERE first_responded_on IS NOT NULL")]
    frts = [m for m in frts if m]
    return {
        "open": len(open_tickets),
        "breached": breached,
        "unassigned": scalar(f"SELECT COUNT(*) FROM tickets WHERE agent_id IS NULL AND status IN ({open_q})", tuple(OPEN_STATUSES)) or 0,
        "resolved_today": scalar("SELECT COUNT(*) FROM tickets WHERE resolved_on >= '2026-06-11'") or 0,
        "avg_first_response": round(sum(frts) / len(frts)) if frts else 0,
        "total": scalar("SELECT COUNT(*) FROM tickets") or 0,
        "csat": _csat(),
    }


def _csat() -> int:
    r = rows("SELECT feedback_rating FROM tickets WHERE feedback_rating IS NOT NULL")
    if not r:
        return 0
    good = sum(1 for x in r if x["feedback_rating"] >= 4)
    return round(100 * good / len(r))


def counts_by(col: str) -> list[dict]:
    return rows(f"SELECT {col} k, COUNT(*) n FROM tickets GROUP BY {col}")


def ticket(tid: int):
    return one(
        """SELECT t.*, c.name customer, ct.name contact_name, a.name agent_name,
                  tm.name team_name
           FROM tickets t
           LEFT JOIN customers c ON c.id=t.customer_id
           LEFT JOIN contacts ct ON ct.id=t.contact_id
           LEFT JOIN agents a ON a.id=t.agent_id
           LEFT JOIN teams tm ON tm.id=t.team_id
           WHERE t.id=?""", (tid,))


def messages_for(tid: int):
    return rows("SELECT * FROM ticket_messages WHERE ticket_id=? ORDER BY created", (tid,))


def activity_for(tid: int):
    return rows("SELECT * FROM ticket_activity WHERE ticket_id=? ORDER BY created DESC", (tid,))
