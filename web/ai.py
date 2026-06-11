"""FastHelpdesk AI assistant — slash-commands + grounded multi-provider chat.

Slash-commands resolve locally against SQLite (no API key). Free-form chat is
streamed from a configurable provider and grounded with a live snapshot of the
support queue so answers reflect the actual tickets and SLAs.
"""
from __future__ import annotations

import json
import os

import db

PROVIDER = os.getenv("MODEL_PROVIDER", "xai")
MODEL = os.getenv("MODEL_NAME", "grok-4-1-fast-reasoning")


def snapshot() -> str:
    k = db.kpis()
    by_status = {r["k"]: r["n"] for r in db.counts_by("status")}
    by_pri = {r["k"]: r["n"] for r in db.counts_by("priority")}
    lines = [
        "CURRENT SUPPORT SNAPSHOT (synthetic demo data):",
        f"- Open tickets: {k['open']} ({k['unassigned']} unassigned). "
        f"SLA at risk (breached/overdue): {k['breached']}.",
        f"- Resolved today: {k['resolved_today']}. Avg first response: {k['avg_first_response']} min. CSAT: {k['csat']}%.",
        "Tickets by status: " + ", ".join(f"{s} {by_status.get(s,0)}" for s in db.TICKET_STATUSES),
        "Tickets by priority: " + ", ".join(f"{p} {by_pri.get(p,0)}" for p in db.PRIORITIES),
    ]
    # name the worst SLA offenders
    open_q = ",".join("?" * len(db.OPEN_STATUSES))
    opens = db.rows(f"SELECT * FROM tickets WHERE status IN ({open_q})", tuple(db.OPEN_STATUSES))
    breached = [t for t in opens if db.sla_state(t)["breached"]]
    if breached:
        lines.append("Examples of SLA-breached open tickets: " +
                     "; ".join(f"#{t['id']} {t['subject'][:40]} ({t['priority']})" for t in breached[:6]))
    return "\n".join(lines)


SYSTEM_PROMPT = """You are the FastHelpdesk assistant, embedded in an open-source customer-support desk.
Help support agents triage tickets, watch SLAs, balance load across teams, and draft replies.
Be concise and practical; use Markdown (short tables, bold figures) when it helps.
All data is synthetic demo data — never claim it is real. Base answers on the SUPPORT SNAPSHOT below;
if something isn't in it, say so plainly rather than inventing."""


def _table(headers, rows_):
    out = ["| " + " | ".join(headers) + " |", "| " + " | ".join("---" for _ in headers) + " |"]
    for r in rows_:
        out.append("| " + " | ".join(str(c) for c in r) + " |")
    return "\n".join(out)


def handle_command(text: str):
    if not text.startswith("/"):
        return None
    parts = text[1:].split()
    cmd = parts[0].lower() if parts else ""
    arg = " ".join(parts[1:])

    if cmd in ("help", "?"):
        return ("**FastHelpdesk shortcuts**\n\n"
                "- `/sla` — open tickets breaching or near SLA\n"
                "- `/tickets [status]` — ticket queue\n"
                "- `/priority <Urgent|High|Medium|Low>` — by priority\n"
                "- `/agents` — agent workload\n"
                "- `/kb [query]` — knowledge-base articles\n"
                "- `/kpi` — headline numbers\n\nOr ask a question in plain English.")

    if cmd == "kpi":
        k = db.kpis()
        return _table(["Metric", "Value"], [
            ["Open tickets", k["open"]], ["Unassigned", k["unassigned"]],
            ["SLA at risk", k["breached"]], ["Resolved today", k["resolved_today"]],
            ["Avg first response (min)", k["avg_first_response"]], ["CSAT", f"{k['csat']}%"]])

    if cmd == "sla":
        open_q = ",".join("?" * len(db.OPEN_STATUSES))
        opens = db.rows(
            f"""SELECT t.*, c.name customer FROM tickets t LEFT JOIN customers c ON c.id=t.customer_id
                WHERE t.status IN ({open_q})""", tuple(db.OPEN_STATUSES))
        risk = [(t, db.sla_state(t)) for t in opens]
        risk = [(t, s) for t, s in risk if s["breached"] or s["tone"] == "warn"]
        risk.sort(key=lambda x: not x[1]["breached"])
        if not risk:
            return "No tickets are breaching or near SLA. 🎉"
        return "**SLA at risk**\n\n" + _table(
            ["#", "Subject", "Customer", "Priority", "SLA"],
            [[f"#{t['id']}", t["subject"][:38], t["customer"], t["priority"], s["label"]] for t, s in risk[:12]])

    if cmd == "tickets":
        if arg:
            rows_ = db.rows(
                """SELECT t.id,t.subject,t.priority,t.status,c.name customer FROM tickets t
                   LEFT JOIN customers c ON c.id=t.customer_id WHERE t.status LIKE ?
                   ORDER BY t.created DESC LIMIT 15""", (f"%{arg}%",))
        else:
            open_q = ",".join("?" * len(db.OPEN_STATUSES))
            rows_ = db.rows(
                f"""SELECT t.id,t.subject,t.priority,t.status,c.name customer FROM tickets t
                    LEFT JOIN customers c ON c.id=t.customer_id WHERE t.status IN ({open_q})
                    ORDER BY t.created DESC LIMIT 15""", tuple(db.OPEN_STATUSES))
        if not rows_:
            return "No tickets found."
        return _table(["#", "Subject", "Customer", "Priority", "Status"],
                      [[f"#{r['id']}", r["subject"][:38], r["customer"], r["priority"], r["status"]] for r in rows_])

    if cmd == "priority":
        pri = arg.title() or "Urgent"
        rows_ = db.rows(
            """SELECT t.id,t.subject,t.status,c.name customer FROM tickets t
               LEFT JOIN customers c ON c.id=t.customer_id WHERE t.priority=? AND t.status IN ('Open','Replied','On Hold')
               ORDER BY t.created DESC LIMIT 15""", (pri,))
        if not rows_:
            return f"No open {pri} tickets."
        return f"**Open {pri} tickets**\n\n" + _table(
            ["#", "Subject", "Customer", "Status"],
            [[f"#{r['id']}", r["subject"][:40], r["customer"], r["status"]] for r in rows_])

    if cmd == "agents":
        rows_ = db.rows(
            """SELECT a.name, tm.name team, a.availability,
                      (SELECT COUNT(*) FROM tickets t WHERE t.agent_id=a.id AND t.status IN ('Open','Replied','On Hold')) open_n
               FROM agents a LEFT JOIN teams tm ON tm.id=a.team_id ORDER BY open_n DESC""")
        return "**Agent workload**\n\n" + _table(
            ["Agent", "Team", "Status", "Open"],
            [[r["name"], r["team"], r["availability"], r["open_n"]] for r in rows_])

    if cmd == "kb":
        clause, params = ("WHERE title LIKE ?", (f"%{arg}%",)) if arg else ("", ())
        rows_ = db.rows(f"SELECT title,views FROM articles {clause} ORDER BY views DESC LIMIT 12", params)
        if not rows_:
            return "No articles found."
        return "**Knowledge base**\n\n" + _table(["Article", "Views"], [[r["title"], f"{r['views']:,}"] for r in rows_])

    return f"Unknown command `/{cmd}`. Try `/help`."


async def stream_chat(message: str):
    cmd = handle_command(message)
    if cmd is not None:
        yield f"data: {json.dumps({'token': cmd})}\n\n"
        yield f"data: {json.dumps({'done': True})}\n\n"
        return
    system = SYSTEM_PROMPT + "\n\n" + snapshot()
    try:
        async for tok in _provider_stream(system, message):
            yield f"data: {json.dumps({'token': tok})}\n\n"
    except Exception as e:  # noqa: BLE001
        yield f"data: {json.dumps({'error': str(e)})}\n\n"
    yield f"data: {json.dumps({'done': True})}\n\n"


async def _provider_stream(system, message):
    import httpx
    provider, model = PROVIDER, MODEL
    if provider in ("xai", "openai"):
        url = "https://api.x.ai/v1/chat/completions" if provider == "xai" else "https://api.openai.com/v1/chat/completions"
        key = os.getenv("XAI_API_KEY" if provider == "xai" else "OPENAI_API_KEY", "")
        if not key:
            yield _no_key(provider); return
        async with httpx.AsyncClient(timeout=90) as client:
            async with client.stream("POST", url, headers={"Authorization": f"Bearer {key}"},
                                     json={"model": model, "stream": True,
                                           "messages": [{"role": "system", "content": system},
                                                        {"role": "user", "content": message}]}) as resp:
                async for line in resp.aiter_lines():
                    if line.startswith("data: ") and line != "data: [DONE]":
                        try:
                            tok = json.loads(line[6:])["choices"][0]["delta"].get("content", "")
                            if tok: yield tok
                        except (json.JSONDecodeError, KeyError, IndexError):
                            pass
    elif provider == "anthropic":
        key = os.getenv("ANTHROPIC_API_KEY", "")
        if not key:
            yield _no_key(provider); return
        async with httpx.AsyncClient(timeout=90) as client:
            async with client.stream("POST", "https://api.anthropic.com/v1/messages",
                                     headers={"x-api-key": key, "anthropic-version": "2023-06-01"},
                                     json={"model": model, "max_tokens": 1500, "stream": True,
                                           "system": system, "messages": [{"role": "user", "content": message}]}) as resp:
                async for line in resp.aiter_lines():
                    if line.startswith("data: "):
                        try:
                            ev = json.loads(line[6:])
                            if ev.get("type") == "content_block_delta":
                                tok = ev.get("delta", {}).get("text", "")
                                if tok: yield tok
                        except json.JSONDecodeError:
                            pass
    elif provider == "google":
        key = os.getenv("GOOGLE_API_KEY", "")
        if not key:
            yield _no_key(provider); return
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:streamGenerateContent?alt=sse&key={key}"
        async with httpx.AsyncClient(timeout=90) as client:
            async with client.stream("POST", url, json={
                "system_instruction": {"parts": [{"text": system}]},
                "contents": [{"role": "user", "parts": [{"text": message}]}]}) as resp:
                async for line in resp.aiter_lines():
                    if line.startswith("data: "):
                        try:
                            tok = json.loads(line[6:])["candidates"][0]["content"]["parts"][0].get("text", "")
                            if tok: yield tok
                        except (json.JSONDecodeError, KeyError, IndexError):
                            pass
    else:
        yield (f"No LLM provider configured (MODEL_PROVIDER='{provider}'). Set it to xai/openai/anthropic/google "
               "in `.env`. Slash-commands like `/sla` work without a key.")


def _no_key(provider):
    env = {"xai": "XAI_API_KEY", "openai": "OPENAI_API_KEY", "anthropic": "ANTHROPIC_API_KEY", "google": "GOOGLE_API_KEY"}[provider]
    return (f"⚠ No **{env}** set, so free-form chat is disabled. Add it to `.env` and restart. "
            "Slash-commands (`/sla`, `/tickets`, `/agents` …) work without any key.")
