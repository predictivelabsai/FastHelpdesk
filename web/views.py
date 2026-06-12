"""Center-pane page renderers for FastHelpdesk."""
from __future__ import annotations

from fasthtml.common import (
    Div, H1, H3, H4, P, Span, A, Table, Thead, Tbody, Tr, Th, Td, Ul, Li,
    Strong, NotStr, Form, Input, Button, Textarea, Select, Option,
)

import db
from web.layout import kpi_card


def _pill(text, kind=""):
    return Span(text, cls="pill " + (kind or str(text)).lower().replace(" ", "").replace("/", ""))


def _sla(t):
    s = db.sla_state(t)
    return Span(s["label"], cls=f"sla {s['tone']}")


def _title(title, sub="", *actions):
    return Div(Div(H1(title), P(sub, cls="sub") if sub else None),
               Div(*actions) if actions else None, cls="page-title")


def _ago(ts):
    return (ts or "")[:16]


# ---------- dashboard -------------------------------------------------------

def dashboard():
    k = db.kpis()
    by_status = {r["k"]: r["n"] for r in db.counts_by("status")}
    by_pri = {r["k"]: r["n"] for r in db.counts_by("priority")}
    max_s = max(by_status.values(), default=1) or 1

    status_funnel = [Div(Div(s, style="color:var(--text-dim);"),
                         Div(Div(cls="funnel-bar", style=f"width:{max(2,100*by_status.get(s,0)/max_s):.0f}%;")),
                         Div(str(by_status.get(s, 0)), cls="v"), cls="funnel-row")
                     for s in db.TICKET_STATUSES]

    pri_rows = Table(Thead(Tr(Th("Priority"), Th("Tickets"), Th("First-resp SLA"), Th("Resolution SLA"))),
                     Tbody(*[Tr(Td(_pill(p)), Td(str(by_pri.get(p, 0))),
                                Td(f"{db.SLA_TARGETS[p][0]//60}h" if db.SLA_TARGETS[p][0] >= 60 else f"{db.SLA_TARGETS[p][0]}m"),
                                Td(f"{db.SLA_TARGETS[p][1]//60}h"))
                             for p in db.PRIORITIES]), cls="tbl")

    # SLA-risk queue: open tickets sorted by closest/most-overdue deadline
    open_q = ",".join("?" * len(db.OPEN_STATUSES))
    open_tickets = db.rows(
        f"""SELECT t.*, c.name customer, a.name agent FROM tickets t
            LEFT JOIN customers c ON c.id=t.customer_id
            LEFT JOIN agents a ON a.id=t.agent_id
            WHERE t.status IN ({open_q})""", tuple(db.OPEN_STATUSES))
    risk = sorted(open_tickets, key=lambda t: db.sla_state(t)["breached"] is False)
    risk = [t for t in open_tickets if db.sla_state(t)["breached"] or db.sla_state(t)["tone"] == "warn"][:8]
    risk_tbl = Table(
        Thead(Tr(Th("#"), Th("Subject"), Th("Customer"), Th("Priority"), Th("SLA"), Th("Agent"))),
        Tbody(*[Tr(Td(A(f"#{t['id']}", href=f"/tickets/{t['id']}")),
                   Td(A(t["subject"][:42], href=f"/tickets/{t['id']}")),
                   Td(t["customer"] or "—"), Td(_pill(t["priority"])), Td(_sla(t)),
                   Td(t["agent"] or Span("Unassigned", style="color:var(--breach);")))
                for t in risk] or [Tr(Td("No SLA risks 🎉", colspan="6"))]), cls="tbl")

    return (
        _title("Support Dashboard", "Live queue health & SLA — fully synthetic demo data."),
        Div(kpi_card("Open tickets", k["open"], f"{k['unassigned']} unassigned"),
            kpi_card("SLA at risk", k["breached"], "breached / overdue", tone="breach"),
            kpi_card("Resolved today", k["resolved_today"], f"avg 1st reply {k['avg_first_response']}m", tone="ok"),
            kpi_card("CSAT", f"{k['csat']}%", "positive ratings", tone="warn" if k["csat"] < 70 else "ok"),
            cls="kpi-grid"),
        Div(Div(Div(H3("Tickets by status"), cls="card-header"), *status_funnel, cls="card"),
            Div(Div(H3("Priority & SLA policy"), cls="card-header"), pri_rows, cls="card"), cls="grid-2"),
        Div(Div(H3("SLA at risk — act now"), cls="card-header"), risk_tbl, cls="card"),
    )


# ---------- tickets ---------------------------------------------------------

def tickets_list(status="Open queue", priority="All", q=""):
    seg = Div(*[A(s, href=f"/tickets?status={s}", cls="" + ("active" if status == s else ""))
                for s in ["Open queue", "All", *db.TICKET_STATUSES]], cls="seg")

    where, params = [], []
    if status == "Open queue":
        where.append(f"t.status IN ({','.join('?'*len(db.OPEN_STATUSES))})")
        params += db.OPEN_STATUSES
    elif status != "All":
        where.append("t.status=?")
        params.append(status)
    if priority != "All":
        where.append("t.priority=?")
        params.append(priority)
    if q:
        where.append("(t.subject LIKE ? OR c.name LIKE ?)")
        params += [f"%{q}%", f"%{q}%"]
    clause = ("WHERE " + " AND ".join(where)) if where else ""
    tickets = db.rows(
        f"""SELECT t.*, c.name customer, a.name agent, tm.name team FROM tickets t
            LEFT JOIN customers c ON c.id=t.customer_id
            LEFT JOIN agents a ON a.id=t.agent_id
            LEFT JOIN teams tm ON tm.id=t.team_id
            {clause} ORDER BY t.created DESC LIMIT 200""", tuple(params))

    pri_seg = Div(Span("Priority: ", style="color:var(--text-mute);font-size:12px;align-self:center;"),
                  *[A(p, href=f"/tickets?status={status}&priority={p}",
                      cls="" + ("active" if priority == p else "")) for p in ["All", *db.PRIORITIES]], cls="seg")

    tbl = Table(
        Thead(Tr(Th("#"), Th("Subject"), Th("Customer"), Th("Priority"), Th("Status"),
                 Th("SLA"), Th("Agent"), Th("Updated"))),
        Tbody(*[Tr(
            Td(A(f"#{t['id']}", href=f"/tickets/{t['id']}")),
            Td(A(t["subject"][:46], href=f"/tickets/{t['id']}")),
            Td(t["customer"] or "—"), Td(_pill(t["priority"])), Td(_pill(t["status"])),
            Td(_sla(t)), Td(t["agent"] or Span("—", style="color:var(--breach);")),
            Td(_ago(t["created"]), style="color:var(--text-mute);"),
        ) for t in tickets] or [Tr(Td("No tickets match.", colspan="8"))]), cls="tbl")

    search = Form(Input(type="search", name="q", value=q, placeholder="Search tickets…"),
                  Input(type="hidden", name="status", value=status), cls="toolbar", method="get", action="/tickets")
    return _title("Tickets", f"{len(tickets)} shown"), seg, pri_seg, search, Div(tbl, cls="card")


def _select(name, options, current, tid, field):
    return Select(*[Option(o, value=o, selected=(o == current)) for o in options],
                  name=name, cls="mini-select",
                  **{"hx-post": f"/tickets/{tid}/field", "hx-vals": f'{{"field":"{field}"}}',
                     "hx-target": "#ticket-main", "hx-swap": "innerHTML", "hx-trigger": "change"})


def ticket_main(tid):
    t = db.ticket(tid)
    if not t:
        return Div(P("No such ticket."))
    msgs = db.messages_for(tid)
    acts = db.activity_for(tid)
    ags = db.agents()

    thread = Div(*[Div(Div(f"{m['author']} · {_ago(m['created'])}", cls="who"),
                       Div(NotStr(m["body"])), cls=f"bubble {m['sender']}") for m in msgs], cls="thread")
    reply = Form(Textarea("", name="body", placeholder="Write a reply to the customer…", required=True),
                 Div(Button("↩ Send reply", cls="btn primary", type="submit", name="sender", value="agent"),
                     Button("🔒 Internal note", cls="btn", type="submit", name="sender", value="note"),
                     style="margin-top:8px;display:flex;gap:8px;"),
                 **{"hx-post": f"/tickets/{tid}/message", "hx-target": "#ticket-main", "hx-swap": "innerHTML"},
                 cls="reply-form")

    agent_sel = Select(Option("Unassigned", value="", selected=not t["agent_id"]),
                       *[Option(a["name"], value=str(a["id"]), selected=(a["id"] == t["agent_id"])) for a in ags],
                       name="agent_id", cls="mini-select",
                       **{"hx-post": f"/tickets/{tid}/assign", "hx-target": "#ticket-main",
                          "hx-swap": "innerHTML", "hx-trigger": "change"})

    info = Div(Div(H3("Ticket"), _sla(t), cls="card-header"),
               Div(Span("Status", cls="k"), _select("status", db.TICKET_STATUSES, t["status"], tid, "status"),
                   Span("Priority", cls="k"), _select("priority", db.PRIORITIES, t["priority"], tid, "priority"),
                   Span("Type", cls="k"), _select("ticket_type", db.TICKET_TYPES, t["ticket_type"] or "Unspecified", tid, "ticket_type"),
                   Span("Agent", cls="k"), agent_sel,
                   Span("Customer", cls="k"), Span(t["customer"] or "—"),
                   Span("Team", cls="k"), Span(t["team_name"] or "—"),
                   Span("Opened", cls="k"), Span(_ago(t["created"])),
                   Span("Resolve by", cls="k"), Span(_ago(t["resolution_by"])),
                   cls="kv"), cls="card")
    timeline = Ul(*[Li(Div(Strong(NotStr(a["action"])), " ", Span(a["actor"] or "", style="color:var(--text-mute);")),
                       Div(_ago(a["created"]), cls="when")) for a in acts] or [Li("No activity.")], cls="timeline")

    return Div(Div(Div(Div(H3("Conversation"), cls="card-header"), thread, reply, cls="card")),
               Div(info, Div(Div(H3("Activity"), cls="card-header"), timeline, cls="card")),
               cls="detail-grid")


def ticket_detail(tid):
    t = db.ticket(tid)
    if not t:
        return _title("Ticket not found"), P("No such ticket.")
    return (_title(t["subject"], f"Ticket #{t['id']}", A("← All tickets", href="/tickets", cls="btn")),
            Div(ticket_main(tid), id="ticket-main"))


# ---------- agents ----------------------------------------------------------

def agents_list():
    agents = db.rows(
        """SELECT a.*, tm.name team,
                  (SELECT COUNT(*) FROM tickets t WHERE t.agent_id=a.id AND t.status IN ('Open','Replied','On Hold')) open_n,
                  (SELECT COUNT(*) FROM tickets t WHERE t.agent_id=a.id AND t.resolved_on>='2026-06-11') solved_today
           FROM agents a LEFT JOIN teams tm ON tm.id=a.team_id ORDER BY open_n DESC""")
    tbl = Table(
        Thead(Tr(Th("Agent"), Th("Team"), Th("Availability"), Th("Open"), Th("Resolved today"))),
        Tbody(*[Tr(Td(Strong(a["name"])), Td(a["team"] or "—"),
                   Td(_pill(a["availability"])), Td(str(a["open_n"])), Td(str(a["solved_today"])))
                for a in agents]), cls="tbl")
    teams = db.rows(
        """SELECT tm.name, COUNT(t.id) open_n FROM teams tm
           LEFT JOIN tickets t ON t.team_id=tm.id AND t.status IN ('Open','Replied','On Hold')
           GROUP BY tm.id ORDER BY open_n DESC""")
    team_tbl = Table(Thead(Tr(Th("Team"), Th("Open tickets"))),
                     Tbody(*[Tr(Td(r["name"]), Td(str(r["open_n"]))) for r in teams]), cls="tbl")
    return (_title("Agents & Teams", f"{len(agents)} agents across {len(teams)} teams"),
            Div(Div(Div(H3("Agents"), cls="card-header"), tbl, cls="card"),
                Div(Div(H3("Teams"), cls="card-header"), team_tbl, cls="card"), cls="grid-2"))


# ---------- knowledge base --------------------------------------------------

def kb_list(q=""):
    cats = db.rows("SELECT * FROM article_categories ORDER BY name")
    clause, params = "", ()
    if q:
        clause = "WHERE a.title LIKE ? OR a.content LIKE ?"
        params = (f"%{q}%", f"%{q}%")
    arts = db.rows(
        f"""SELECT a.*, ac.name category FROM articles a
            LEFT JOIN article_categories ac ON ac.id=a.category_id
            {clause} ORDER BY a.views DESC""", params)
    by_cat = {}
    for a in arts:
        by_cat.setdefault(a["category"] or "Other", []).append(a)
    blocks = []
    for cat in sorted(by_cat):
        items = [Div(H4(a["title"]),
                     Div(f"{a['category']} · {a['views']:,} views · by {a['author']}", cls="meta"),
                     cls="kb-card") for a in by_cat[cat]]
        blocks.append(Div(Div(H3(cat), cls="card-header"), *items, cls="card"))
    search = Form(Input(type="search", name="q", value=q, placeholder="Search the knowledge base…"),
                  cls="toolbar", method="get", action="/kb")
    return _title("Knowledge Base", f"{len(arts)} published articles"), search, *blocks


# ---------- customers -------------------------------------------------------

def customers_list():
    custs = db.rows(
        """SELECT c.*, COUNT(t.id) tickets,
                  SUM(CASE WHEN t.status IN ('Open','Replied','On Hold') THEN 1 ELSE 0 END) open_n
           FROM customers c LEFT JOIN tickets t ON t.customer_id=c.id
           GROUP BY c.id ORDER BY open_n DESC, tickets DESC""")
    tbl = Table(Thead(Tr(Th("Customer"), Th("Domain"), Th("Total tickets"), Th("Open"))),
                Tbody(*[Tr(Td(Strong(c["name"])), Td(c["domain"] or "—"),
                           Td(str(c["tickets"])), Td(str(c["open_n"] or 0))) for c in custs]), cls="tbl")
    return _title("Customers", f"{len(custs)} accounts"), Div(tbl, cls="card")
