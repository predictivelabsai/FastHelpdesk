"""FastHelpdesk public reads and token-gated integration writes."""

import db

from .api_core import Resource, SQLiteBackend, create_sqlite_api

RESOURCES = (
    Resource("tickets", "tickets", "Tickets", "Customer support tickets and SLA workflow state.", search_fields=("subject", "description", "status", "priority")),
    Resource("customers", "customers", "Customers", "Support customer organisations.", search_fields=("name", "domain")),
    Resource("knowledge", "articles", "Knowledge articles", "Published and draft support knowledge.", search_fields=("title", "content", "author", "status")),
    Resource("canned-responses", "canned_responses", "Canned responses", "Reusable agent response templates.", write_fields=("title", "body"), search_fields=("title", "body")),
)

backend = SQLiteBackend(db.DB_PATH, RESOURCES, initialize=db.init_schema)
api = create_sqlite_api(
    product="FastHelpdesk", version="1.0.0",
    description="Open integration access to FastHelpdesk tickets, customers, and support knowledge.",
    base_url="https://helpdesk.fastsme.com", backend=backend, resources=RESOURCES,
)
