from datetime import date, datetime
import uuid

from qzwhatnext.engine.ranking import stack_rank
from qzwhatnext.models.task import Task, TaskCategory


def test_due_by_increases_urgency_within_tier(sample_task_base):
    now = datetime(2026, 1, 26, 12, 0, 0)

    no_due = Task(
        **{
            **sample_task_base,
            "id": str(uuid.uuid4()),
            "title": "No due",
            "category": TaskCategory.HOME,
            "deadline": None,
            "due_by": None,
        }
    )
    due = Task(
        **{
            **sample_task_base,
            "id": str(uuid.uuid4()),
            "title": "Due soon",
            "category": TaskCategory.HOME,
            "deadline": None,
            "due_by": date(2026, 1, 27),
        }
    )

    ranked = stack_rank([no_due, due], now=now, time_zone="UTC")
    assert ranked[0].id == due.id

