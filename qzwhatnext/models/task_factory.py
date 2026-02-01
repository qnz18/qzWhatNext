"""Task creation factory for qzWhatNext.

This module centralizes task creation logic to eliminate duplication
and ensure consistent default values across the application.
"""

import uuid
from datetime import date, datetime
from typing import Optional, Dict, Any

from qzwhatnext.models.task import Task, TaskStatus, TaskCategory
from qzwhatnext.models.constants import (
    DEFAULT_DURATION_MINUTES,
    DEFAULT_DURATION_CONFIDENCE,
    DEFAULT_RISK_SCORE,
    DEFAULT_IMPACT_SCORE,
    DEFAULT_ENERGY_INTENSITY,
)


def determine_ai_exclusion(title: str) -> bool:
    """Determine if a task should be AI-excluded based on title.
    
    A task is AI-excluded if its title starts with a period (`.`).
    
    Args:
        title: Task title to check
        
    Returns:
        True if task should be AI-excluded, False otherwise
    """
    return title.startswith('.') if title else False


def create_task_defaults() -> Dict[str, Any]:
    """Get default task values as a dictionary.
    
    Returns:
        Dictionary with default task field values using constants
    """
    return {
        "status": TaskStatus.OPEN,
        "deadline": None,
        "start_after": None,
        "due_by": None,
        "estimated_duration_min": DEFAULT_DURATION_MINUTES,
        "duration_confidence": DEFAULT_DURATION_CONFIDENCE,
        "category": TaskCategory.UNKNOWN,
        "energy_intensity": DEFAULT_ENERGY_INTENSITY,
        "risk_score": DEFAULT_RISK_SCORE,
        "impact_score": DEFAULT_IMPACT_SCORE,
        "dependencies": [],
        "flexibility_window": None,
        "ai_excluded": False,
        "manual_priority_locked": False,
        "user_locked": False,
        "manually_scheduled": False,
    }


def create_task_base(
    user_id: str,
    source_type: str,
    source_id: Optional[str],
    title: str,
    notes: Optional[str] = None,
    deadline: Optional[datetime] = None,
    start_after: Optional[date] = None,
    due_by: Optional[date] = None,
    estimated_duration_min: Optional[int] = None,
    duration_confidence: Optional[float] = None,
    category: Optional[TaskCategory] = None,
    energy_intensity: Optional[Any] = None,
    risk_score: Optional[float] = None,
    impact_score: Optional[float] = None,
    dependencies: Optional[list] = None,
    flexibility_window: Optional[tuple] = None,
    ai_excluded: Optional[bool] = None,
    manual_priority_locked: Optional[bool] = None,
    user_locked: Optional[bool] = None,
    manually_scheduled: Optional[bool] = None,
) -> Task:
    """Create a task with defaults, allowing overrides.
    
    This function centralizes task creation logic and applies defaults
    from constants. All optional parameters override defaults when provided.
    
    Args:
        user_id: User ID who owns this task (required)
        source_type: Source system type (e.g., 'api', 'google_sheets')
        source_id: External ID in source system (None for API-created tasks)
        title: Task title (required)
        notes: Task notes or description
        deadline: Task deadline
        estimated_duration_min: Estimated duration in minutes (defaults to constant)
        duration_confidence: Confidence in duration estimate (defaults to constant)
        category: Task category (defaults to UNKNOWN)
        energy_intensity: Energy intensity (defaults to constant)
        risk_score: Risk of negative consequence (defaults to constant)
        impact_score: Downstream impact score (defaults to constant)
        dependencies: List of dependent task IDs
        flexibility_window: Earliest start and latest end times
        ai_excluded: Whether task is excluded from AI processing (auto-determined if None)
        manual_priority_locked: Whether priority is manually locked
        user_locked: Whether task is user-locked
        manually_scheduled: Whether task is manually scheduled
        
    Returns:
        Task object with defaults applied
    """
    now = datetime.utcnow()
    defaults = create_task_defaults()
    
    # Determine AI exclusion if not explicitly provided
    if ai_excluded is None:
        ai_excluded = determine_ai_exclusion(title)
    
    # Apply defaults, allowing overrides
    task = Task(
        id=str(uuid.uuid4()),
        user_id=user_id,
        source_type=source_type,
        source_id=source_id,
        title=title,
        notes=notes,
        status=defaults["status"],
        created_at=now,
        updated_at=now,
        deadline=deadline if deadline is not None else defaults["deadline"],
        start_after=start_after if start_after is not None else defaults["start_after"],
        due_by=due_by if due_by is not None else defaults["due_by"],
        estimated_duration_min=estimated_duration_min if estimated_duration_min is not None else defaults["estimated_duration_min"],
        duration_confidence=duration_confidence if duration_confidence is not None else defaults["duration_confidence"],
        category=category if category is not None else defaults["category"],
        energy_intensity=energy_intensity if energy_intensity is not None else defaults["energy_intensity"],
        risk_score=risk_score if risk_score is not None else defaults["risk_score"],
        impact_score=impact_score if impact_score is not None else defaults["impact_score"],
        dependencies=dependencies if dependencies is not None else defaults["dependencies"],
        flexibility_window=flexibility_window if flexibility_window is not None else defaults["flexibility_window"],
        ai_excluded=ai_excluded,
        manual_priority_locked=manual_priority_locked if manual_priority_locked is not None else defaults["manual_priority_locked"],
        user_locked=user_locked if user_locked is not None else defaults["user_locked"],
        manually_scheduled=manually_scheduled if manually_scheduled is not None else defaults["manually_scheduled"],
    )
    
    return task

