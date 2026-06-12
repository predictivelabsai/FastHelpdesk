"""Generate a fully synthetic FastHelpdesk database (deterministic, no PII)."""
from __future__ import annotations

import random
from datetime import datetime, timedelta

import db

RNG = random.Random(20260611)
NOW = datetime(2026, 6, 11, 12, 0, 0)


def _dt(mins_ago: float) -> str:
    return (NOW - timedelta(minutes=mins_ago)).strftime("%Y-%m-%d %H:%M:%S")


AGENT_NAMES = ["Priya Nair", "Tom Becker", "Lena Sokolova", "Marco Bianchi",
               "Aisha Bello", "Kenji Watanabe", "Sara Lindholm", "Diego Ramos"]
TEAMS = ["Frontline", "Billing", "Technical", "Onboarding"]
CUST_NAMES = ["Northwind Retail", "Apex Logistics", "Lumen Health", "Helios Energy",
              "Vertex Digital", "Cobalt Foods", "Bluewave Media", "Sterling Bank",
              "Quanta Labs", "Evergreen Group", "Meridian Travel", "Ironclad Security"]
SUBJECTS = [
    ("Cannot log in to the dashboard", "Incident", "Urgent"),
    ("Invoice shows wrong tax amount", "Bug", "High"),
    ("How do I export my data to CSV?", "Question", "Low"),
    ("API returns 500 on bulk upload", "Bug", "Urgent"),
    ("Request: dark mode for reports", "Feature Request", "Low"),
    ("Payment failed but card was charged", "Incident", "Urgent"),
    ("Onboarding: how to invite my team", "Question", "Medium"),
    ("Email notifications not arriving", "Incident", "High"),
    ("Report scheduler stuck since morning", "Incident", "High"),
    ("Need to change billing address", "Question", "Low"),
    ("Two-factor codes not being accepted", "Incident", "Urgent"),
    ("Slow page loads on the orders view", "Bug", "Medium"),
    ("Where can I find the audit log?", "Question", "Low"),
    ("Webhook deliveries are duplicated", "Bug", "High"),
    ("Upgrade plan and add 5 seats", "Question", "Medium"),
    ("Data import skipped 40 rows", "Bug", "Medium"),
    ("Mobile app crashes on startup", "Incident", "High"),
    ("Feature: bulk-assign tickets", "Feature Request", "Low"),
]
CUST_MSG = [
    "Hi team, this started happening this morning and is blocking our work. Please help!",
    "Steps to reproduce are attached. Let me know what else you need.",
    "This is urgent for us — we have customers waiting.",
    "Thanks in advance. Happy to hop on a call if that's easier.",
    "It worked fine last week, so something must have changed.",
]
AGENT_MSG = [
    "Thanks for reaching out — I'm looking into this now and will update you shortly.",
    "I've reproduced the issue and escalated it to our engineering team.",
    "Could you confirm which browser and version you're using?",
    "A fix has been deployed. Could you try again and confirm it's resolved?",
    "I've applied a temporary workaround on our side; you should be unblocked now.",
]
NOTE_MSG = [
    "Internal: likely related to yesterday's deploy. Pinging on-call.",
    "Internal: customer is on the Enterprise plan — prioritise.",
    "Internal: known issue, tracked in JIRA-1423.",
]
ARTICLES = [
    ("Getting started: your first 10 minutes", "Onboarding"),
    ("How to invite and manage your team", "Onboarding"),
    ("Exporting data to CSV and Excel", "Using the product"),
    ("Setting up two-factor authentication", "Account & security"),
    ("Understanding your invoice and taxes", "Billing"),
    ("Changing your plan and adding seats", "Billing"),
    ("Configuring email notifications", "Using the product"),
    ("Using the API: authentication & rate limits", "Developers"),
    ("Webhooks: setup and retry behaviour", "Developers"),
    ("Troubleshooting login problems", "Account & security"),
    ("Scheduling and sharing reports", "Using the product"),
    ("Data import: supported formats and limits", "Using the product"),
]


def build():
    db.init_schema()
    with db.cursor() as conn:
        for t in ("chat_messages", "canned_responses", "escalation_rules",
                  "ticket_activity", "ticket_messages", "tickets",
                  "articles", "article_categories", "contacts", "customers",
                  "agents", "teams"):
            conn.execute(f"DELETE FROM {t}")
        conn.executemany("INSERT INTO teams(name) VALUES (?)", [(t,) for t in TEAMS])
        team_ids = [r[0] for r in conn.execute("SELECT id FROM teams").fetchall()]

    agents = []
    for i, nm in enumerate(AGENT_NAMES):
        email = nm.lower().replace(" ", ".") + "@fasthelpdesk.example"
        agents.append((nm, email, RNG.choice(team_ids),
                       RNG.choice(db.AGENT_AVAILABILITY), 1))
    with db.cursor() as conn:
        conn.executemany(
            "INSERT INTO agents(name,email,team_id,availability,is_active) VALUES (?,?,?,?,?)", agents)
        agent_ids = [r[0] for r in conn.execute("SELECT id FROM agents").fetchall()]

    customers = [(nm, nm.lower().replace(" ", "") + ".example", _dt(RNG.randint(10000, 500000)))
                 for nm in CUST_NAMES]
    with db.cursor() as conn:
        conn.executemany("INSERT INTO customers(name,domain,created) VALUES (?,?,?)", customers)
        cust_rows = conn.execute("SELECT id,name,domain FROM customers").fetchall()

    contacts = []
    for c in cust_rows:
        for _ in range(RNG.randint(1, 3)):
            fn = RNG.choice(["Alex", "Sam", "Jordan", "Robin", "Casey", "Morgan", "Riley", "Jamie"])
            ln = RNG.choice(["Cooper", "Patel", "Nguyen", "Garcia", "Schmidt", "Khan", "Rossi"])
            contacts.append((f"{fn} {ln}", f"{fn.lower()}@{c['domain']}", c["id"]))
    with db.cursor() as conn:
        conn.executemany("INSERT INTO contacts(name,email,customer_id) VALUES (?,?,?)", contacts)
        contact_rows = conn.execute("SELECT id,customer_id,name,email FROM contacts").fetchall()
    contacts_by_cust = {}
    for c in contact_rows:
        contacts_by_cust.setdefault(c["customer_id"], []).append(c)

    # knowledge base
    cats = sorted({c for _, c in ARTICLES})
    with db.cursor() as conn:
        conn.executemany("INSERT INTO article_categories(name,icon) VALUES (?,?)",
                         [(c, "📘") for c in cats])
        cat_ids = {r["name"]: r["id"] for r in conn.execute("SELECT id,name FROM article_categories").fetchall()}
        arts = [(title, cat_ids[cat],
                 f"## {title}\n\nThis article explains **{title.lower()}** step by step. "
                 "It is synthetic demo content for FastHelpdesk.\n\n1. Open the relevant screen.\n"
                 "2. Follow the on-screen prompts.\n3. Save your changes.",
                 RNG.choice(AGENT_NAMES), "Published", RNG.randint(20, 4000),
                 _dt(RNG.randint(10000, 300000)))
                for title, cat in ARTICLES]
        conn.executemany(
            """INSERT INTO articles(title,category_id,content,author,status,views,published_on)
               VALUES (?,?,?,?,?,?,?)""", arts)

    # tickets
    status_weights = [("Open", 22), ("Replied", 16), ("On Hold", 6),
                      ("Resolved", 30), ("Closed", 26)]
    statuses = [s for s, w in status_weights for _ in range(w)]
    tickets, n = [], 70
    for i in range(n):
        subj, ttype, pri = RNG.choice(SUBJECTS)
        cust = RNG.choice(cust_rows)
        contact = RNG.choice(contacts_by_cust.get(cust["id"], [None]))
        status = RNG.choice(statuses)
        # Open tickets are recent (a live queue); closed ones can be older.
        if status in db.OPEN_STATUSES:
            created_min = RNG.randint(15, 3600)        # up to ~2.5 days
        else:
            created_min = RNG.randint(120, 20000)
        resp_target, res_target = db.SLA_TARGETS[pri]
        created = NOW - timedelta(minutes=created_min)
        response_by = created + timedelta(minutes=resp_target)
        resolution_by = created + timedelta(minutes=res_target)
        # responded? most tickets beyond brand-new have a first response
        first_resp = None
        if status != "Open" or RNG.random() < 0.5:
            # sometimes breach the response SLA
            lateness = RNG.choice([0.3, 0.6, 0.9, 1.2, 1.8])
            first_resp = created + timedelta(minutes=resp_target * lateness)
        resolved = None
        rating = None
        if status in db.CLOSED_STATUSES:
            lateness = RNG.choice([0.4, 0.7, 1.0, 1.1, 1.6])
            resolved = created + timedelta(minutes=res_target * lateness)
            if resolved > NOW:
                resolved = NOW - timedelta(minutes=RNG.randint(10, 2000))
            # land a chunk of resolutions in "today" for a lively dashboard
            elif RNG.random() < 0.4:
                resolved = NOW - timedelta(minutes=RNG.randint(30, 700))
            rating = RNG.choices([5, 4, 3, 2, 1], weights=[40, 30, 15, 8, 7])[0]
        agent_id = None if (status == "Open" and RNG.random() < 0.5) else RNG.choice(agent_ids)
        tickets.append((
            subj, RNG.choice(CUST_MSG), status, pri, ttype, cust["id"],
            contact["id"] if contact else None,
            contact["email"] if contact else f"user@{cust['domain']}",
            RNG.choice(team_ids), agent_id,
            created.strftime("%Y-%m-%d %H:%M:%S"),
            response_by.strftime("%Y-%m-%d %H:%M:%S"),
            resolution_by.strftime("%Y-%m-%d %H:%M:%S"),
            first_resp.strftime("%Y-%m-%d %H:%M:%S") if first_resp else None,
            resolved.strftime("%Y-%m-%d %H:%M:%S") if resolved else None,
            rating,
        ))
    with db.cursor() as conn:
        conn.executemany(
            """INSERT INTO tickets
               (subject,description,status,priority,ticket_type,customer_id,contact_id,
                raised_by,team_id,agent_id,created,response_by,resolution_by,
                first_responded_on,resolved_on,feedback_rating)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", tickets)
        trows = conn.execute("SELECT id,description,created,first_responded_on,resolved_on,agent_id,status FROM tickets").fetchall()

    # conversation + activity
    msgs, acts = [], []
    for t in trows:
        msgs.append((t["id"], "customer", "Customer", t["description"], t["created"]))
        acts.append((t["id"], "Ticket created", "Customer", t["created"]))
        if t["first_responded_on"]:
            msgs.append((t["id"], "agent", "Agent", RNG.choice(AGENT_MSG), t["first_responded_on"]))
            acts.append((t["id"], "First response sent", "Agent", t["first_responded_on"]))
            if RNG.random() < 0.5:
                msgs.append((t["id"], "note", "Agent", RNG.choice(NOTE_MSG), t["first_responded_on"]))
        if t["resolved_on"]:
            msgs.append((t["id"], "agent", "Agent", RNG.choice(AGENT_MSG), t["resolved_on"]))
            acts.append((t["id"], f"Marked {t['status']}", "Agent", t["resolved_on"]))
    with db.cursor() as conn:
        conn.executemany(
            "INSERT INTO ticket_messages(ticket_id,sender,author,body,created) VALUES (?,?,?,?,?)", msgs)
        conn.executemany(
            "INSERT INTO ticket_activity(ticket_id,action,actor,created) VALUES (?,?,?,?)", acts)

    # canned responses
    canned = [
        ("Acknowledge & investigate",
         "Hi {{customer}},\n\nThanks for getting in touch about \"{{subject}}\". I'm looking into this "
         "now and will get back to you shortly with an update.\n\nBest regards,\n{{agent}}"),
        ("Ask for more details",
         "Hi {{customer}},\n\nTo help me resolve this quickly, could you share:\n- the steps that led to "
         "the issue\n- any error messages you saw\n- a screenshot if possible\n\nThanks,\n{{agent}}"),
        ("Resolved — confirm",
         "Hi {{customer}},\n\nThis should now be resolved. Could you confirm everything is working on your "
         "side? I'll close the ticket once you're happy.\n\nThanks,\n{{agent}}"),
        ("Escalating to specialist",
         "Hi {{customer}},\n\nI've escalated \"{{subject}}\" to our specialist team so it gets the right "
         "attention. They'll follow up directly.\n\nBest,\n{{agent}}"),
    ]
    with db.cursor() as conn:
        conn.executemany(
            "INSERT INTO canned_responses(title,body,created) VALUES (?,?,datetime('now'))", canned)
        # escalation rules
        conn.executemany(
            "INSERT INTO escalation_rules(name,priority_filter,trigger,action,target_team_id,enabled,created) "
            "VALUES (?,?,?,?,?,?,datetime('now'))",
            [("Urgent unanswered → raise", "Any", "Response overdue", "Set Urgent", None, 1),
             ("Unassigned high → bump", "High", "Unassigned", "Raise priority", None, 1),
             ("Resolution overdue → escalate team", "Any", "Resolution overdue", "Assign to team", team_ids[0], 0)])

    print(f"FastHelpdesk seeded → {db.DB_PATH}")
    print(f"  {len(agents)} agents · {len(TEAMS)} teams · {len(customers)} customers · "
          f"{n} tickets · {len(arts)} articles · {len(msgs)} messages")
    print(f"  {len(canned)} canned replies · 3 escalation rules")


if __name__ == "__main__":
    build()
