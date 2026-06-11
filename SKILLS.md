# Skills

Capability reference for FastHelpdesk, plus the shared **Frappe → FastHTML
migration playbook** (identical recipe across the `fasthtml-oss-migrations`
apps — see also `FastCRM/SKILLS.md`).

---

## Part 1 — FastHelpdesk capabilities

**Entry:** `python web_app.py` → http://localhost:5007
(login `admin@fasthelpdesk.example` / `FastHelpdesk2026$`).

3-pane FastHTML layout: left nav · center work area · right AI rail.

### Pages

| View | Route | What it shows |
|---|---|---|
| Dashboard | `/` | KPIs (open, SLA-at-risk, resolved today, CSAT), tickets by status, SLA policy, "SLA at risk" worklist |
| Tickets | `/tickets?status=&priority=&q=` | Filterable/searchable queue with live SLA badges |
| Ticket | `/tickets/{id}` | Conversation (customer/agent/note), SLA timers, activity log |
| Agents & Teams | `/agents` | Per-agent and per-team workload + availability |
| Knowledge Base | `/kb?q=` | Published articles by category |
| Customers | `/customers` | Accounts ranked by open tickets |
| AI Assistant | `/ai` | Landing; chat is the right rail |

### SLA engine (`db.py`)

`SLA_TARGETS` maps each priority to `(first_response_min, resolution_min)`.
`sla_state(ticket)` returns a live `{label, tone, breached}` against the clock:
*Response due in 2h* (ok), *…due in 45m* (warn), *Resolution overdue 1d*
(breach). The dashboard's "SLA at risk" list and the queue's badges both use it.

### AI assistant (`web/ai.py`)

- **Slash-commands** (no API key): `/sla` `/tickets [status]` `/priority <p>`
  `/agents` `/kb [query]` `/kpi` `/help`.
- **Free-form chat** streams from `MODEL_PROVIDER` (xai|openai|anthropic|google),
  grounded with a live `snapshot()` (queue counts, SLA breaches, busiest teams)
  so triage answers cite real tickets.

### Data model

`agents · teams · customers · contacts · tickets · ticket_messages ·
ticket_activity · articles · article_categories · chat_messages`. Rebuild with
`python seed.py` (deterministic, no PII).

---

## Part 2 — Frappe → FastHTML migration playbook

The repeatable recipe (FastHelpdesk and FastCRM were both built this way):

1. **Mine the source schema** — `python scripts/frappe_doctype_to_schema.py
   /tmp/frappe-helpdesk` turns Frappe DocType JSON into starting SQLite DDL
   (maps fieldtypes, resolves Links, skips layout fields).
2. **Collapse, don't replicate** — fold Frappe's normalised status/priority
   doctypes into `TEXT` columns + Python vocabularies in `db.py`.
3. **FastHTML shell** — `fast_app(pico=False, hdrs=[Style(CSS)])` (don't
   double-load htmx); one `page()` helper wraps every view; a `_guard()` redirect
   handles auth without Beforeware.
4. **HTMX over JS** — links + `hx_get`/`hx_post`; vanilla JS only for the SSE
   chat reader, kept in `layout.py`.
5. **Synthetic data** — fixed RNG seed; app self-seeds on first boot.
6. **Multi-provider LLM, key-optional** — reuse `web/ai.py` `_provider_stream`;
   slash-commands must work with no key.
7. **Capture the demo** — drive with Playwright MCP → frames →
   `bash scripts/build_demo_gif.sh` → README GIF.
8. **Ship deploy paths** — `.env.sample`, `Dockerfile`, `docker-compose.yml`
   (named volume so the DB outlives image rebuilds).

### Reusable assets

| File | Reuse |
|---|---|
| `scripts/frappe_doctype_to_schema.py` | DocType JSON → SQLite DDL (any Frappe app) |
| `scripts/build_demo_gif.sh` | PNG frames → demo GIF |
| `web/layout.py` | 3-pane shell + CSS tokens + SSE chat JS |
| `web/ai.py` `_provider_stream()` | 4-provider streaming chat dispatch |
| `db.py` `sla_state()` | live SLA/deadline badge logic (reusable for any deadline-driven app) |
