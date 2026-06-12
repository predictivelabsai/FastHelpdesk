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
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
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
CREATE TABLE IF NOT EXISTS canned_responses (
    id            INTEGER PRIMARY KEY,
    title         TEXT NOT NULL,
    body          TEXT NOT NULL,
    created       TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS escalation_rules (
    id              INTEGER PRIMARY KEY,
    name            TEXT NOT NULL,
    priority_filter TEXT NOT NULL DEFAULT 'Any',   -- 'Any' | a priority
    trigger         TEXT NOT NULL,                 -- Response overdue | Resolution overdue | Unassigned
    action          TEXT NOT NULL,                 -- Raise priority | Set Urgent | Assign to team
    target_team_id  INTEGER REFERENCES teams(id),
    enabled         INTEGER NOT NULL DEFAULT 1,
    created         TEXT NOT NULL
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


def agents() -> list[dict]:
    return rows("SELECT a.id, a.name, t.name team FROM agents a LEFT JOIN teams t ON t.id=a.team_id "
                "WHERE a.is_active=1 ORDER BY a.name")


# --- write operations (transactional) ---------------------------------------

def _log(tid, action, actor="Agent"):
    with cursor() as conn:
        conn.execute("INSERT INTO ticket_activity(ticket_id,action,actor,created) VALUES(?,?,?,datetime('now'))",
                     (tid, action, actor))


def add_message(tid: int, sender: str, body: str, author: str = "Agent"):
    """sender: 'agent' (reply) | 'note' (internal) | 'customer'."""
    if not body.strip():
        return
    with cursor() as conn:
        conn.execute("INSERT INTO ticket_messages(ticket_id,sender,author,body,created) "
                     "VALUES(?,?,?,?,datetime('now'))", (tid, sender, author, body.strip()))
        # an agent reply sets first_responded_on (if unset) and moves Open→Replied
        if sender == "agent":
            t = conn.execute("SELECT first_responded_on, status FROM tickets WHERE id=?", (tid,)).fetchone()
            if t and not t[0]:
                conn.execute("UPDATE tickets SET first_responded_on=datetime('now') WHERE id=?", (tid,))
            if t and t[1] == "Open":
                conn.execute("UPDATE tickets SET status='Replied' WHERE id=?", (tid,))
    _log(tid, "Reply sent" if sender == "agent" else "Internal note added")


def set_ticket_field(tid: int, field: str, value: str):
    allowed = {"status": TICKET_STATUSES, "priority": PRIORITIES, "ticket_type": TICKET_TYPES}
    if field not in allowed or value not in allowed[field]:
        return False
    closed = ", resolved_on=datetime('now')" if (field == "status" and value in CLOSED_STATUSES) else ""
    with cursor() as conn:
        conn.execute(f"UPDATE tickets SET {field}=?{closed} WHERE id=?", (value, tid))
    _log(tid, f"{field.replace('_',' ').title()} changed to <strong>{value}</strong>")
    return True


def assign_agent(tid: int, agent_id):
    with cursor() as conn:
        if agent_id:
            a = conn.execute("SELECT name FROM agents WHERE id=?", (agent_id,)).fetchone()
            conn.execute("UPDATE tickets SET agent_id=? WHERE id=?", (agent_id, tid))
            msg = f"Assigned to <strong>{a[0] if a else 'agent'}</strong>"
        else:
            conn.execute("UPDATE tickets SET agent_id=NULL WHERE id=?", (tid,))
            msg = "Unassigned"
    _log(tid, msg)


# --- canned responses -------------------------------------------------------

def canned_responses():
    return rows("SELECT * FROM canned_responses ORDER BY title")


def create_canned_response(title: str, body: str) -> int | None:
    title, body = (title or "").strip(), (body or "").strip()
    if not title or not body:
        return None
    with cursor() as conn:
        conn.execute("INSERT INTO canned_responses(title,body,created) VALUES (?,?,datetime('now'))",
                     (title, body))
        return conn.execute("SELECT last_insert_rowid()").fetchone()[0]


def delete_canned_response(cid: int):
    with cursor() as conn:
        conn.execute("DELETE FROM canned_responses WHERE id=?", (cid,))


def render_canned(body: str, ticket: dict) -> str:
    """Substitute {{customer}}, {{agent}}, {{subject}} placeholders for preview."""
    return (body
            .replace("{{customer}}", ticket.get("contact_name") or ticket.get("customer") or "there")
            .replace("{{agent}}", ticket.get("agent_name") or "the support team")
            .replace("{{subject}}", ticket.get("subject") or "your request"))


# --- escalation rules -------------------------------------------------------

ESCALATION_TRIGGERS = ["Response overdue", "Resolution overdue", "Unassigned"]
ESCALATION_ACTIONS = ["Raise priority", "Set Urgent", "Assign to team"]
_PRIORITY_LADDER = ["Low", "Medium", "High", "Urgent"]


def _now() -> datetime:
    return datetime(2026, 6, 11, 12, 0, 0)


def escalation_rules():
    return rows("""SELECT e.*, tm.name target_team FROM escalation_rules e
                   LEFT JOIN teams tm ON tm.id=e.target_team_id ORDER BY e.id""")


def create_escalation_rule(name, priority_filter, trigger, action, target_team_id=None) -> int | None:
    if trigger not in ESCALATION_TRIGGERS or action not in ESCALATION_ACTIONS:
        return None
    pf = priority_filter if priority_filter in PRIORITIES else "Any"
    tt = int(target_team_id) if (action == "Assign to team" and target_team_id) else None
    with cursor() as conn:
        conn.execute("""INSERT INTO escalation_rules(name,priority_filter,trigger,action,target_team_id,enabled,created)
                        VALUES (?,?,?,?,?,1,datetime('now'))""",
                     ((name or "Rule").strip(), pf, trigger, action, tt))
        return conn.execute("SELECT last_insert_rowid()").fetchone()[0]


def toggle_escalation_rule(rid: int):
    with cursor() as conn:
        conn.execute("UPDATE escalation_rules SET enabled = 1-enabled WHERE id=?", (rid,))


def delete_escalation_rule(rid: int):
    with cursor() as conn:
        conn.execute("DELETE FROM escalation_rules WHERE id=?", (rid,))


def _rule_matches(rule, t, now) -> bool:
    if t["status"] not in OPEN_STATUSES:
        return False
    if rule["priority_filter"] != "Any" and t["priority"] != rule["priority_filter"]:
        return False
    trig = rule["trigger"]
    if trig == "Response overdue":
        rb = _parse(t.get("response_by"))
        return (not t.get("first_responded_on")) and bool(rb) and rb < now
    if trig == "Resolution overdue":
        rb = _parse(t.get("resolution_by"))
        return (not t.get("resolved_on")) and bool(rb) and rb < now
    if trig == "Unassigned":
        return t.get("agent_id") is None
    return False


def _apply_escalation_action(rule, t):
    """Apply a rule's action to ticket dict t (mutating it), return a description
    or None if it was already satisfied (no-op)."""
    action = rule["action"]
    if action == "Raise priority":
        i = _PRIORITY_LADDER.index(t["priority"]) if t["priority"] in _PRIORITY_LADDER else 0
        if i >= len(_PRIORITY_LADDER) - 1:
            return None
        newp = _PRIORITY_LADDER[i + 1]
        with cursor() as conn:
            conn.execute("UPDATE tickets SET priority=? WHERE id=?", (newp, t["id"]))
        t["priority"] = newp
        desc = f"priority raised to {newp}"
    elif action == "Set Urgent":
        if t["priority"] == "Urgent":
            return None
        with cursor() as conn:
            conn.execute("UPDATE tickets SET priority='Urgent' WHERE id=?", (t["id"],))
        t["priority"] = "Urgent"
        desc = "priority set to Urgent"
    elif action == "Assign to team":
        if not rule["target_team_id"] or t.get("team_id") == rule["target_team_id"]:
            return None
        with cursor() as conn:
            conn.execute("UPDATE tickets SET team_id=? WHERE id=?", (rule["target_team_id"], t["id"]))
        t["team_id"] = rule["target_team_id"]
        desc = f"reassigned to team {rule['target_team']}"
    else:
        return None
    _log(t["id"], f"⚡ Escalated by rule <strong>{rule['name']}</strong>: {desc}", actor="Automation")
    return desc


def apply_escalations() -> list[dict]:
    """Run all enabled rules over open tickets; return what was changed."""
    now = _now()
    rules = [r for r in escalation_rules() if r["enabled"]]
    open_q = ",".join("?" * len(OPEN_STATUSES))
    tickets = rows(f"SELECT * FROM tickets WHERE status IN ({open_q})", tuple(OPEN_STATUSES))
    by_id = {t["id"]: t for t in tickets}
    out = []
    for rule in rules:
        for t in by_id.values():
            if not _rule_matches(rule, t, now):
                continue
            desc = _apply_escalation_action(rule, t)
            if desc:
                out.append({"ticket_id": t["id"], "subject": t["subject"],
                            "rule": rule["name"], "detail": desc})
    return out
