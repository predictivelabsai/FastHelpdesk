# FastHelpdesk Roadmap — Frappe Helpdesk feature comparison

FastHelpdesk ports the **core** of [Frappe Helpdesk](https://github.com/frappe/helpdesk)
(~42 doctypes) to a FastHTML demonstrator. This records what's implemented and
what's deferred.

## Implemented ✅

| Capability | Upstream doctype(s) | FastHelpdesk |
|---|---|---|
| Tickets | `HD Ticket` | `tickets` with status/priority/type |
| Ticket statuses | `HD Ticket Status` (Open/Paused/Resolved) | Open · Replied · On Hold · Resolved · Closed |
| Priorities | `HD Ticket Priority` | Urgent · High · Medium · Low |
| Conversation | comments + email communications | `ticket_messages` (customer / agent / internal note) |
| Activity log | `HD Ticket Activity` | `ticket_activity` |
| **SLA timers** | `HD Service Level Agreement` / `…Priority` | `db.SLA_TARGETS` + live response/resolution state |
| Agents | `HD Agent` (+ availability) | `agents` |
| Teams | `HD Team` | `teams`, workload per team |
| Customers | `HD Customer` | `customers` |
| Knowledge base | `HD Article` / `HD Article Category` | `articles` / `article_categories` |
| CSAT | `HD Ticket Feedback` | `feedback_rating` → CSAT KPI |
| **Canned responses** | `HD Canned Response` | `canned_responses` + one-click insert with {{placeholders}} |
| **Escalation rules** | `HD Escalation Rule` | `escalation_rules` + a run engine that raises priority / reassigns |
| **AI assistant** | *(not upstream)* | grounded multi-provider chat + triage |

## Near-term roadmap 🔜

1. ✅ **Write operations** (done) — HTMX
   reply box, internal-note composer, status/priority change, and **assign to
   agent** with optimistic SLA recompute.
2. **Ticket templates & types** — `HD Ticket Template`/`…Field` (structured
   intake forms per ticket type).
3. ✅ **Escalation rules** (done) — define rules (priority filter + trigger:
   response/resolution overdue or unassigned → action: raise priority, set
   urgent, or reassign to a team), enable/disable them, and "Run escalations"
   applies them across the open queue, logging each change to the ticket
   timeline as an Automation action. Time-based auto-running still to come.
4. ✅ **Canned responses** (done) — a managed library of reply templates with
   `{{customer}}`/`{{agent}}`/`{{subject}}` placeholders; on a ticket they show
   as chips that insert the (resolved) text into the reply box.
5. **Article feedback & search** — `HD Article Feedback`, `HD Stopword`/
   `HD Synonym` (helpful/not-helpful + better KB search).
6. **Customer portal** — upstream has an agent desk *and* a customer portal; add
   a read-only "my tickets" view for contacts.

## Later / out-of-scope 🗓️

- **Email ingestion** — `Email Account`, inbound email → ticket, threaded
  reply-by-email (needs a mail server; mirrors FastMail).
- **Business-hours/holiday SLA math** — `HD Service Day`, `HD Service Holiday
  List` (FastHelpdesk uses wall-clock targets, not working-hours-aware ones).
- **Assignment rules** — round-robin/load-based auto-assignment.
- **ERPNext bridge** — `ERPNext HD Settings`.
- **Form scripts / field layouts** — `HD Form Script`, `HD Field Layout`
  (runtime low-code customisation; a Frappe-framework feature).

## Design notes

The SLA engine is the headline feature: targets per priority in
`db.SLA_TARGETS`, evaluated live in `db.sla_state()` so the dashboard and queue
sort by what's about to breach. Upstream makes working-hours-aware SLAs via
holiday lists and service days — FastHelpdesk keeps wall-clock targets for
legibility; a working-hours calendar is the natural next upgrade.
