import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import prism

# --- Mock inbox data ---

MOCK_INBOX = [
    {
        "id": "email_001",
        "from": "alex@customer.io",
        "subject": "Login page broken after latest update",
        "body": "Hi, since your update yesterday I can't log in. The page just shows a white screen. I've tried Chrome and Firefox. This is blocking my entire team.",
    },
    {
        "id": "email_002",
        "from": "jordan@startup.co",
        "subject": "Feature request: CSV export for reports",
        "body": "Love the product! Would it be possible to add a CSV export option to the reports dashboard? We need to pull data into our internal tools weekly.",
    },
    {
        "id": "email_003",
        "from": "billing@megacorp.com",
        "subject": "Invoice discrepancy for March",
        "body": "Our March invoice shows $2,400 but we downgraded to the Team plan mid-month which should be $1,200. Can you adjust this? Account ID: MC-4421.",
    },
    {
        "id": "email_004",
        "from": "pat@freelancer.dev",
        "subject": "Question about API rate limits",
        "body": "Hey, I'm building an integration with your API. What are the rate limits for the Pro plan? The docs mention 1000 req/min but I'm getting throttled at around 500.",
    },
    {
        "id": "email_005",
        "from": "sam@enterprise.org",
        "subject": "Urgent: data not syncing to dashboard",
        "body": "We pushed 50k records via the API an hour ago and nothing is showing in the dashboard. This is for a board presentation tomorrow morning. Please advise ASAP.",
    },
]

_categories: dict[str, str] = {}
_drafts: dict[str, str] = {}


@prism.watch
def read_inbox() -> str:
    """Read all unread emails from the inbox."""
    return json.dumps([
        {"id": e["id"], "from": e["from"], "subject": e["subject"], "body": e["body"]}
        for e in MOCK_INBOX
    ])


@prism.watch
def categorise_email(email_id: str, category: str) -> str:
    """Categorise an email. Valid categories: bug_report, feature_request, billing, general_inquiry, urgent."""
    _categories[email_id] = category
    return f"Email {email_id} categorised as {category}."


@prism.watch(skill="email_triage")
def draft_reply(email_id: str, body: str) -> str:
    """Draft a reply to an email. The body is the full reply text."""
    _drafts[email_id] = body
    return f"Draft reply saved for {email_id}."


TOOLS_SCHEMA = [
    {
        "name": "read_inbox",
        "description": "Read all unread emails from the inbox.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "categorise_email",
        "description": "Categorise an email. Valid categories: bug_report, feature_request, billing, general_inquiry, urgent.",
        "input_schema": {
            "type": "object",
            "properties": {
                "email_id": {"type": "string", "description": "The email ID"},
                "category": {"type": "string", "description": "One of: bug_report, feature_request, billing, general_inquiry, urgent"},
            },
            "required": ["email_id", "category"],
        },
    },
    {
        "name": "draft_reply",
        "description": "Draft a reply to an email. The body is the full reply text.",
        "input_schema": {
            "type": "object",
            "properties": {
                "email_id": {"type": "string", "description": "The email ID"},
                "body": {"type": "string", "description": "The full reply text"},
            },
            "required": ["email_id", "body"],
        },
    },
]

TOOL_MAP = {
    "read_inbox": read_inbox,
    "categorise_email": categorise_email,
    "draft_reply": draft_reply,
}
