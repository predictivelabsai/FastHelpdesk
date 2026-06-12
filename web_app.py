"""FastHelpdesk — an open-source customer-support desk built with FastHTML.

A server-side, HTMX-driven port of the core of Frappe Helpdesk: a ticket queue
with live SLA timers, ticket conversations, agents & teams, a knowledge base,
customers, and an AI assistant grounded in the live (synthetic) queue.

Run:
    python web_app.py            # http://localhost:5007

Login: admin@fasthelpdesk.example / FastHelpdesk2026$  (override via .env)
"""
from __future__ import annotations

import os
import json
import secrets
import uuid
import logging

from dotenv import load_dotenv
load_dotenv()

from fasthtml.common import (
    fast_app, serve, Div, H1, P, A, Form, Input, Button, NotStr,
    RedirectResponse, Script, Style, Link, Title,
)
from starlette.responses import StreamingResponse, Response

import db
from web.layout import page, LAYOUT_CSS
from web import views, ai

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s — %(message)s")
logger = logging.getLogger("fasthelpdesk")

VALID_EMAIL = os.getenv("FASTHELPDESK_ADMIN_EMAIL", "admin@fasthelpdesk.example")
VALID_PASSWORD = os.getenv("FASTHELPDESK_ADMIN_PASSWORD", "FastHelpdesk2026$")
ENV_LABEL = os.getenv("FASTHELPDESK_ENV_LABEL", "FastHelpdesk")
SECRET = os.getenv("FASTHELPDESK_SECRET", secrets.token_hex(32))
PORT = int(os.getenv("FASTHELPDESK_PORT", "5007"))

app, rt = fast_app(live=False, pico=False, secret_key=SECRET, hdrs=[Style(LAYOUT_CSS)])


def _user(session):
    return session.get("user")


def _thread(session):
    if "thread" not in session:
        session["thread"] = uuid.uuid4().hex
    return session["thread"]


def _guard(session, active, builder):
    if not _user(session):
        return RedirectResponse("/login", status_code=303)
    content = builder() if callable(builder) else builder
    if not isinstance(content, tuple):
        content = (content,)
    return page(active, ENV_LABEL, _user(session), _thread(session), *content)


def _login_card(error="", email=""):
    return Title("FastHelpdesk — Sign in"), Style(LAYOUT_CSS), Div(
        Form(H1("FastHelpdesk"), P("Sign in to your support desk"),
             Input(name="email", type="email", placeholder="Email", value=email, required=True),
             Input(name="password", type="password", placeholder="Password", required=True),
             P(error, cls="error") if error else None,
             Button("Sign in", cls="btn primary", type="submit"),
             P(NotStr("Demo: <code>admin@fasthelpdesk.example</code> / <code>FastHelpdesk2026$</code>"), cls="hint"),
             method="post", action="/login", cls="login-card"), cls="login-wrap")


@rt("/login")
def get(session):
    if _user(session):
        return RedirectResponse("/", status_code=303)
    return _login_card()


@rt("/login")
def post(session, email: str = "", password: str = ""):
    if email.strip().lower() == VALID_EMAIL.lower() and password == VALID_PASSWORD:
        session["user"] = email.strip().lower()
        return RedirectResponse("/", status_code=303)
    return _login_card("Invalid email or password.", email)


@rt("/logout")
def get(session):
    session.pop("user", None)
    return RedirectResponse("/login", status_code=303)


@rt("/")
def get(session):
    return _guard(session, "dashboard", views.dashboard)


@rt("/tickets")
def get(session, status: str = "Open queue", priority: str = "All", q: str = ""):
    return _guard(session, "tickets", lambda: views.tickets_list(status, priority, q))


@rt("/tickets/{tid}")
def get(session, tid: int):
    return _guard(session, "tickets", lambda: views.ticket_detail(tid))


def _tfrag(session, tid):
    if not _user(session):
        return Response("Unauthorized", status_code=401)
    return views.ticket_main(tid)


@rt("/tickets/{tid}/message")
def post(session, tid: int, body: str = "", sender: str = "agent"):
    db.add_message(tid, "note" if sender == "note" else "agent", body)
    return _tfrag(session, tid)


@rt("/tickets/{tid}/field")
def post(session, tid: int, field: str = "", status: str = "", priority: str = "", ticket_type: str = ""):
    val = {"status": status, "priority": priority, "ticket_type": ticket_type}.get(field, "")
    db.set_ticket_field(tid, field, val)
    return _tfrag(session, tid)


@rt("/tickets/{tid}/assign")
def post(session, tid: int, agent_id: str = ""):
    db.assign_agent(tid, int(agent_id) if agent_id else None)
    return _tfrag(session, tid)


@rt("/agents")
def get(session):
    return _guard(session, "agents", views.agents_list)


@rt("/kb")
def get(session, q: str = ""):
    return _guard(session, "kb", lambda: views.kb_list(q))


@rt("/customers")
def get(session):
    return _guard(session, "customers", views.customers_list)


# --- canned replies ---------------------------------------------------------

@rt("/canned")
def get(session):
    return _guard(session, "canned", views.canned_list)


@rt("/canned/new")
def post(session, title: str = "", body: str = ""):
    if not _user(session):
        return RedirectResponse("/login", status_code=303)
    db.create_canned_response(title, body)
    return RedirectResponse("/canned", status_code=303)


@rt("/canned/{cid}/delete")
def post(session, cid: int):
    if not _user(session):
        return RedirectResponse("/login", status_code=303)
    db.delete_canned_response(cid)
    return RedirectResponse("/canned", status_code=303)


# --- escalation rules -------------------------------------------------------

@rt("/escalations")
def get(session):
    return _guard(session, "escalations", views.escalations_view)


@rt("/escalations/new")
def post(session, name: str = "", priority_filter: str = "Any", trigger: str = "",
         action: str = "", target_team_id: str = ""):
    if not _user(session):
        return RedirectResponse("/login", status_code=303)
    db.create_escalation_rule(name, priority_filter, trigger, action, target_team_id or None)
    return RedirectResponse("/escalations", status_code=303)


@rt("/escalations/{rid}/toggle")
def post(session, rid: int):
    if not _user(session):
        return RedirectResponse("/login", status_code=303)
    db.toggle_escalation_rule(rid)
    return RedirectResponse("/escalations", status_code=303)


@rt("/escalations/{rid}/delete")
def post(session, rid: int):
    if not _user(session):
        return RedirectResponse("/login", status_code=303)
    db.delete_escalation_rule(rid)
    return RedirectResponse("/escalations", status_code=303)


@rt("/escalations/run")
def post(session):
    if not _user(session):
        return RedirectResponse("/login", status_code=303)
    result = db.apply_escalations()
    return _guard(session, "escalations", lambda: views.escalations_view(result))


@rt("/ai")
def get(session):
    body = (views._title("AI Assistant", "Chat lives in the right rail. Ask in plain English or use slash-commands."),
            Div(NotStr(
                "<div class='card'><h3>What you can ask</h3><ul style='line-height:1.8;'>"
                "<li>“Which tickets are breaching SLA right now?”</li>"
                "<li>“Who has the heaviest workload?”</li>"
                "<li>“Summarise today's support load.”</li>"
                "<li>“Find knowledge-base articles about billing.”</li></ul>"
                "<p style='color:var(--text-mute)'>Slash-commands resolve instantly with no API key: "
                "<code>/sla</code> <code>/tickets</code> <code>/priority</code> <code>/agents</code> "
                "<code>/kb</code> <code>/kpi</code> <code>/help</code></p></div>")))
    return _guard(session, "ai", body)


@rt("/guide")
def get(session):
    body = (views._title("User Guide", "How to drive FastHelpdesk"), Div(NotStr("""
<div class='card'><h3>Dashboard</h3><p>Queue health KPIs (open, SLA at risk, resolved today, CSAT),
tickets by status, your priority/SLA policy, and an "SLA at risk" worklist.</p></div>
<div class='card'><h3>Tickets</h3><p>Filter by status and priority, search, and open any ticket for the
full customer conversation, internal notes, SLA timers, and an activity log. SLA badges show
<em>due in</em> / <em>overdue</em> live against each ticket's priority policy.</p></div>
<div class='card'><h3>Agents & Teams</h3><p>Workload per agent and per team, with availability.</p></div>
<div class='card'><h3>Knowledge Base & Customers</h3><p>Published help articles by category, and your
customer accounts ranked by open tickets.</p></div>
<div class='card'><h3>AI Assistant</h3><p>The right rail chats over a live snapshot of the queue.
Set <code>MODEL_PROVIDER</code> + an API key in <code>.env</code> for free-form chat; slash-commands always work.</p></div>
""")))
    return _guard(session, "guide", body)


@rt("/chat/new")
def get(session):
    session["thread"] = uuid.uuid4().hex
    return P("Ask about tickets, SLAs, agents or the knowledge base — or tap a question below.",
             cls="chat-empty-hint")


@rt("/chat/stream")
async def post(session, message: str = "", thread_id: str = ""):
    if not _user(session):
        return Response("Unauthorized", status_code=401)
    message = (message or "").strip()
    if not message:
        return Response("No message", status_code=400)
    tid = thread_id or _thread(session)

    async def gen():
        with db.cursor() as conn:
            conn.execute("INSERT INTO chat_messages(thread_id,role,content,created) VALUES(?,?,?,datetime('now'))",
                         (tid, "user", message))
        full = []
        async for chunk in ai.stream_chat(message):
            if chunk.startswith("data: "):
                try:
                    tok = json.loads(chunk[6:]).get("token")
                    if tok:
                        full.append(tok)
                except Exception:
                    pass
            yield chunk
        with db.cursor() as conn:
            conn.execute("INSERT INTO chat_messages(thread_id,role,content,created) VALUES(?,?,?,datetime('now'))",
                         (tid, "assistant", "".join(full)))

    return StreamingResponse(gen(), media_type="text/event-stream")


def _ensure_db():
    if not db.db_exists():
        logger.info("No database found — seeding synthetic data…")
        import seed
        seed.build()
    else:
        db.init_schema()  # idempotent; creates canned_responses / escalation_rules


_ensure_db()

if __name__ == "__main__":
    logger.info("FastHelpdesk on http://localhost:%s  (login %s)", PORT, VALID_EMAIL)
    serve(port=PORT, reload=os.getenv("FASTHELPDESK_RELOAD", "0") == "1")
