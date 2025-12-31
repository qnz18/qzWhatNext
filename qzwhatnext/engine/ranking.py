"""Stack ranking logic for qzWhatNext.

Sorts tasks by priority tier, then by deadline urgency within each tier.
This produces a deterministic ordering for scheduling.
"""

from datetime import datetime
from typing import List
from qzwhatnext.models.task import Task
from qzwhatnext.engine.tiering import assign_tier


def stack_rank(tasks: List[Task]) -> List[Task]:
    """Stack-rank tasks by tier and deadline urgency.
    
    Tasks are sorted:
    1. By tier (lowest tier number = highest priority)
    2. Within tier, by deadline urgency (earliest deadline first)
    3. Tasks without deadlines go after those with deadlines
    
    This function is deterministic - same inputs always produce same outputs.
    
    Args:
        tasks: List of tasks to rank
        
    Returns:
        List of tasks sorted by priority (highest first)
    """
    # Assign tiers to all tasks
    tasks_with_tiers = [(task, assign_tier(task)) for task in tasks]
    
    # Sort by tier (ascending - lower tier number = higher priority)
    # Then by deadline urgency within tier
    sorted_tasks = sorted(
        tasks_with_tiers,
        key=lambda x: (_tier_sort_key(x[1]), _deadline_sort_key(x[0]))
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


def _deadline_sort_key(task: Task) -> tuple:
    """Get sort key for deadline urgency.
    
    Tasks with deadlines come before those without.
    Among tasks with deadlines, earlier deadlines come first.
    
    Args:
        task: Task to get sort key for
        
    Returns:
        Tuple for sorting: (has_deadline: 0 or 1, deadline_timestamp or max)
    """
    if task.deadline:
        # Tasks with deadlines: use deadline timestamp
        # Earlier deadlines = smaller timestamp = higher priority
        return (0, task.deadline.timestamp())
    else:
        # Tasks without deadlines: use max timestamp to sort after all deadlines
        return (1, float('inf'))

