"""Canonical static interview-question list (P2.4 de-duplication).

Single source of truth for the 9 default DISCOVER interview categories.

Consumers:
- ``frontend/backend/workflow_bridge.py`` — Web UI fallback when the graph's
  interrupt payload carries no dynamic questions.
- ``graph/nodes/discover_interview.py`` — graph-side generic fallback when
  the LLM can't tailor questions for a short description.

Each entry uses the **bridge schema** (``category`` / ``label`` /
``question`` / ``placeholder`` / ``required``) because the Web UI is the
authoritative renderer. Graph-side consumers convert to their own
``key`` / ``label`` / ``prompt`` schema via ``to_graph_schema()``.

Do NOT edit the question text in a consumer — extend this module instead.
"""

from __future__ import annotations

# ── The 9 interview categories (interview-me SKILL.md) ──────────────
INTERVIEW_QUESTIONS: list[dict] = [
    {
        "category": "core_behavior",
        "label": "Core Behavior",
        "question": "What does this feature do? What are the inputs and outputs? What are the success and failure paths?",
        "placeholder": "e.g. Users can create an account, log in, and manage their profile...",
        "required": True,
    },
    {
        "category": "data_model",
        "label": "Data Model",
        "question": "What entities are involved? What fields do they have? Are there relationships to existing models?",
        "placeholder": "e.g. User(id, name, email, password_hash), Order(id, user_id, items, status)...",
        "required": True,
    },
    {
        "category": "api_surface",
        "label": "API Surface",
        "question": "What HTTP methods, paths, and parameters? Any authentication/authorization requirements?",
        "placeholder": "e.g. POST /api/users, GET /api/users/{id}, JWT auth required...",
        "required": True,
    },
    {
        "category": "validation",
        "label": "Validation",
        "question": "What input validation rules? What error responses?",
        "placeholder": "e.g. Email must be valid, password min 8 chars, return 422 on bad input...",
        "required": False,
    },
    {
        "category": "ui_template",
        "label": "UI / Templates",
        "question": "Are there Jinja2 templates involved? What data do they display? Any styling or component requirements?",
        "placeholder": "e.g. Login form, dashboard page, use existing CSS framework...",
        "required": False,
    },
    {
        "category": "integration",
        "label": "Integration",
        "question": "Does this feature interact with other services, databases, or external APIs?",
        "placeholder": "e.g. PostgreSQL for users, Redis for sessions, Stripe for payments...",
        "required": False,
    },
    {
        "category": "deployment",
        "label": "Deployment",
        "question": "Any Docker or infrastructure implications? Environment variables, volumes, or network configuration?",
        "placeholder": "e.g. Docker Compose with API + DB, .env for secrets...",
        "required": False,
    },
    {
        "category": "edge_cases",
        "label": "Edge Cases",
        "question": "What are the known edge cases? What should happen with invalid input, missing data, or rate limits?",
        "placeholder": "e.g. Duplicate email registration, concurrent login attempts...",
        "required": False,
    },
    {
        "category": "non_functional",
        "label": "Non-Functional",
        "question": "Performance targets, security requirements, logging/monitoring needs?",
        "placeholder": "e.g. <200ms response time, rate limiting, audit logging...",
        "required": False,
    },
]


def to_graph_schema(questions: list[dict] | None = None) -> list[dict]:
    """Convert bridge-schema questions to the graph-side schema.

    The graph's ``_generate_interview_questions`` and the interrupt payload
    use ``{"key", "label", "prompt"}``; the Web UI uses
    ``{"category", "label", "question", "placeholder", "required"}``.
    This function performs the mapping so both consumers share one list.
    """
    qs = questions if questions is not None else INTERVIEW_QUESTIONS
    out: list[dict] = []
    for q in qs:
        out.append(
            {
                "key": q["category"],
                "label": q["label"],
                "prompt": q["question"],
            }
        )
    return out
