"""AI exclusion enforcement for qzWhatNext.

This module enforces the critical rule that certain tasks must never be sent to AI.
This is a trust-critical component and must be checked BEFORE any AI calls.
"""

from qzwhatnext.models.task import Task


def is_ai_excluded(task: Task) -> bool:
    """Check if a task is excluded from AI processing.
    
    A task is AI-excluded if:
    1. Its title begins with a period (`.`)
    2. OR it is explicitly flagged as ai_excluded
    
    Args:
        task: The task to check
        
    Returns:
        True if the task should be excluded from AI, False otherwise
        
    Note:
        This function must be called BEFORE any AI inference calls.
        AI-excluded tasks:
        - Are never sent to AI
        - Never receive AI-updated attributes
        - Never change tiers due to AI inference
        - May still be scheduled deterministically
    """
    # Check for period prefix
    if task.title.startswith('.'):
        return True
    
    # Check explicit exclusion flag
    if task.ai_excluded:
        return True
    
    return False


def filter_ai_excluded(tasks: list[Task]) -> tuple[list[Task], list[Task]]:
    """Separate tasks into AI-allowed and AI-excluded lists.
    
    Args:
        tasks: List of tasks to filter
        
    Returns:
        Tuple of (ai_allowed_tasks, ai_excluded_tasks)
    """
    ai_allowed = []
    ai_excluded = []
    
    for task in tasks:
        if is_ai_excluded(task):
            ai_excluded.append(task)
        else:
            ai_allowed.append(task)
    
    return ai_allowed, ai_excluded

