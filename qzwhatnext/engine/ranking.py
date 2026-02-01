"""Stack ranking logic for qzWhatNext.

Sorts tasks by priority tier, then by deadline urgency within each tier.
This produces a deterministic ordering for scheduling.
"""

from datetime import datetime, time, timezone
from typing import List, Optional
from zoneinfo import ZoneInfo
from qzwhatnext.models.task import Task
from qzwhatnext.engine.tiering import assign_tier


def stack_rank(tasks: List[Task], *, now: Optional[datetime] = None, time_zone: str = "UTC") -> List[Task]:
    """Stack-rank tasks by tier and urgency (deadline/due_by) within tier.
    
    Tasks are sorted:
    1. By tier (lowest tier number = highest priority)
    2. Within tier, by urgency: deadline first, then due_by, then none
    3. Stable tie-breakers (created_at, id)
    
    This function is deterministic - same inputs always produce same outputs.
    
    Args:
        tasks: List of tasks to rank
        
    Returns:
        List of tasks sorted by priority (highest first)
    """
    now = now or datetime.utcnow()

    # Assign tiers to all tasks
    tasks_with_tiers = [(task, assign_tier(task)) for task in tasks]
    
    # Sort by tier (ascending - lower tier number = higher priority)
    # Then by deadline urgency within tier
    sorted_tasks = sorted(
        tasks_with_tiers,
        key=lambda x: (
            _tier_sort_key(x[1]),
            _urgency_sort_key(x[0], now=now, time_zone=time_zone),
            _stable_sort_key(x[0]),
        )
    )
    
    # Return just the tasks (without tier numbers)
    return [task for task, _ in sorted_tasks]


def _tier_sort_key(tier: int) -> int:
    """Get sort key for tier (lower = higher priority).
    
    Args:
        tier: Tier number (1-9)
        
    Returns:
        Sort key (tier number itself, since lower = higher priority)
    """
    return tier


def _urgency_sort_key(task: Task, *, now: datetime, time_zone: str) -> tuple:
    """Get sort key for urgency within a tier.

    Ordering:
    - Tasks with deadline first (earliest deadline first)
    - Then tasks with due_by (end-of-day in user's timezone; earliest first)
    - Then tasks with neither
    """
    if task.deadline:
        return (0, _to_utc_naive(task.deadline).timestamp())

    if task.due_by:
        due_dt = _due_by_end_of_day_utc_naive(task.due_by, time_zone=time_zone)
        # Use timestamp (earlier due date -> higher priority). If overdue, it will naturally rise.
        return (1, due_dt.timestamp())

    return (2, float("inf"))


def _stable_sort_key(task: Task) -> tuple:
    created = task.created_at.timestamp() if getattr(task, "created_at", None) else float("inf")
    return (created, task.id)


def _to_utc_naive(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


def _due_by_end_of_day_utc_naive(due_by, *, time_zone: str) -> datetime:
    """Convert date-only due_by into end-of-day UTC-naive datetime using user's timezone."""
    try:
        tz = ZoneInfo(time_zone)
    except Exception:
        tz = ZoneInfo("UTC")
    local_end = datetime.combine(due_by, time(23, 59, 59), tzinfo=tz)
    return local_end.astimezone(timezone.utc).replace(tzinfo=None)

