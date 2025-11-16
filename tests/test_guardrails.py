from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app.categorizer import categorize_task, categorize_urgency
from app.models import TaskRaw, Domain, Urgency, Effort, Impact


def _make_basic_task(**overrides) -> TaskRaw:
    now = datetime.now(timezone.utc).isoformat()
    base: TaskRaw = {
        "id": "test-1",
        "content": "Some task",
        "description": "",
        "due": None,
        "priority": 1,
        "labels": [],
        "project_id": "proj",
        "created_at": now,
    }
    base.update(overrides)
    return base


def test_categorize_task_returns_valid_enums() -> None:
    task = _make_basic_task(content="Go to the gym")
    result = categorize_task(task)

    assert result["domain"] in Domain.__args__
    assert result["urgency"] in Urgency.__args__
    assert result["effort"] in Effort.__args__
    assert result["impact"] in Impact.__args__


def test_overdue_task_is_not_someday() -> None:
    yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    task = _make_basic_task(content="Pay bill", due=yesterday)

    urgency = categorize_urgency(task)
    assert urgency in ("URGENT", "NEAR_TERM")