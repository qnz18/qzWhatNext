from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import List

from .models import TaskRaw


def get_tasks() -> List[TaskRaw]:
    """
    Stubbed Todoist client for early development and testing.

    Later this will make real HTTP calls to the Todoist API.
    """
    now = datetime.now(timezone.utc)

    return [
        TaskRaw(
            id="1",
            content="Meal prep on Sunday",
            description="Prep lunches for the week",
            due=None,
            priority=1,
            labels=[],
            project_id="home",
            created_at=now.isoformat(),
        ),
        TaskRaw(
            id="2",
            content="Go to the gym",
            description="Leg day",
            due=(now + timedelta(days=-1)).isoformat(),  # overdue
            priority=1,
            labels=[],
            project_id="health",
            created_at=now.isoformat(),
        ),
        TaskRaw(
            id="3",
            content="Pay water bill",
            description="Online payment",
            due=(now + timedelta(days=2)).isoformat(),
            priority=2,
            labels=[],
            project_id="finance",
            created_at=now.isoformat(),
        ),
    ]