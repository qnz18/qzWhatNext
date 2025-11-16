from __future__ import annotations

from datetime import datetime, timezone
from typing import cast

from .models import (
    TaskRaw,
    TaskCategorized,
    Domain,
    Urgency,
    Effort,
    Impact,
)


def categorize_task(task: TaskRaw) -> TaskCategorized:
    """
    Main entrypoint for categorization.
    Applies simple, rule-based logic for domain, urgency, effort, impact.
    """
    domain = categorize_domain(task)
    urgency = categorize_urgency(task)
    effort = categorize_effort(task)
    impact = categorize_impact(task)

    categorized: TaskCategorized = {
        **task,
        "domain": domain,
        "urgency": urgency,
        "effort": effort,
        "impact": impact,
    }
    return categorized


def categorize_domain(task: TaskRaw) -> Domain:
    text = f"{task['content']} {task.get('description', '')}".lower()

    if any(k in text for k in ["gym", "workout", "run", "walk", "bike", "ride", "climb", "yoga"]):
        return "HEALTH_FITNESS"
    if any(k in text for k in ["meal prep", "cook", "lunch", "dinner", "grocery", "groceries", "recipe"]):
        return "MEAL_FOOD"
    if any(k in text for k in ["kids", "school", "homework", "playdate", "birthday"]):
        return "FAMILY_KIDS"
    if any(k in text for k in ["tax", "bill", "invoice", "bank", "insurance"]):
        return "FINANCE_ADMIN"
    if any(k in text for k in ["clean", "organize", "fix", "repair", "plumber", "electrician"]):
        return "HOME_MAINTENANCE"
    if any(k in text for k in ["course", "study", "practice", "read", "reading"]):
        return "PERSONAL_DEV"
    if any(k in text for k in ["deck", "presentation", "jira", "sprint", "meeting"]):
        return "WORK"

    return "OTHER"


def categorize_urgency(task: TaskRaw) -> Urgency:
    """
    Simple heuristic:
    - No due date -> SOMEDAY
    - Overdue / due today -> URGENT
    - Due in <= 3 days -> NEAR_TERM
    - Due in <= 14 days -> SOON
    - Else -> SOMEDAY
    """
    due_str = task.get("due")
    if not due_str:
        return "SOMEDAY"

    try:
        due_dt = datetime.fromisoformat(due_str.replace("Z", "+00:00"))
    except Exception:
        # If parsing fails, treat as SOMEDAY but you could log this later
        return "SOMEDAY"

    now = datetime.now(timezone.utc)
    delta_days = (due_dt.date() - now.date()).days

    if delta_days <= 0:
        return "URGENT"
    if delta_days <= 3:
        return "NEAR_TERM"
    if delta_days <= 14:
        return "SOON"
    return "SOMEDAY"


def categorize_effort(task: TaskRaw) -> Effort:
    text = f"{task['content']} {task.get('description', '')}".lower()

    tiny_keywords = ["email", "call", "text", "renew", "pay"]
    large_keywords = ["plan", "design", "research", "write outline", "strategy"]

    if any(k in text for k in tiny_keywords):
        return "TINY"
    if any(k in text for k in large_keywords):
        return "LARGE"

    # Simple fallback for now
    return "SMALL"


def categorize_impact(task: TaskRaw) -> Impact:
    text = f"{task['content']} {task.get('description', '')}".lower()

    if any(k in text for k in ["deadline", "tax", "presentation", "review", "license", "exam"]):
        return "HIGH"
    if any(k in text for k in ["maybe", "idea", "browse", "check out"]):
        return "LOW"

    return "MEDIUM"