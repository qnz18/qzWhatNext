"""Task data model for qzWhatNext."""

from datetime import date, datetime
from typing import List, Optional, Tuple
from enum import Enum
from pydantic import BaseModel, Field


class TaskStatus(str, Enum):
    """Task status enumeration."""
    OPEN = "open"
    COMPLETED = "completed"
    MISSED = "missed"  # Recurrence occurrence passed without completion (habit roll-forward)


class TaskCategory(str, Enum):
    """Task category enumeration."""
    WORK = "work"
    CHILD = "child"
    FAMILY = "family"
    HEALTH = "health"
    PERSONAL = "personal"
    IDEAS = "ideas"
    HOME = "home"
    ADMIN = "admin"
    UNKNOWN = "unknown"


class EnergyIntensity(str, Enum):
    """Energy intensity enumeration."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class Task(BaseModel):
    """Canonical Task model."""
    
    id: str = Field(..., description="Unique task identifier (UUID v4)")
    user_id: str = Field(..., description="User ID who owns this task")
    source_type: str = Field(..., description="Source system type (e.g., 'google_sheets', 'api', 'todoist')")
    source_id: Optional[str] = Field(None, description="External ID in source system (null for API-created tasks)")
    title: str = Field(..., description="Task title")
    notes: Optional[str] = Field(None, description="Task notes or description")
    status: TaskStatus = Field(TaskStatus.OPEN, description="Task status")
    created_at: datetime = Field(..., description="Task creation timestamp")
    updated_at: datetime = Field(..., description="Task last update timestamp")
    deleted_at: Optional[datetime] = Field(None, description="Soft-delete timestamp (null if active)")
    deadline: Optional[datetime] = Field(None, description="Task deadline")
    start_after: Optional[date] = Field(
        None,
        description="Do not schedule before this date (date-only; interpreted in user's calendar timezone)",
    )
    due_by: Optional[date] = Field(
        None,
        description="Soft due date for urgency ranking (date-only; interpreted in user's calendar timezone)",
    )
    estimated_duration_min: int = Field(30, description="Estimated duration in minutes")
    duration_confidence: float = Field(0.5, ge=0.0, le=1.0, description="Confidence in duration estimate")
    category: TaskCategory = Field(TaskCategory.UNKNOWN, description="Task category")
    energy_intensity: EnergyIntensity = Field(EnergyIntensity.MEDIUM, description="Energy intensity")
    risk_score: float = Field(0.3, ge=0.0, le=1.0, description="Risk of negative consequence")
    impact_score: float = Field(0.3, ge=0.0, le=1.0, description="Downstream impact score")
    dependencies: List[str] = Field(default_factory=list, description="List of dependent task IDs")
    flexibility_window: Optional[Tuple[datetime, datetime]] = Field(
        None, 
        description="Earliest start and latest end times"
    )
    ai_excluded: bool = Field(False, description="Whether task is excluded from AI processing")
    manual_priority_locked: bool = Field(False, description="Whether priority is manually locked")
    user_locked: bool = Field(False, description="Whether task is user-locked")
    manually_scheduled: bool = Field(False, description="Whether task is manually scheduled")

    # Recurrence linkage (optional)
    recurrence_series_id: Optional[str] = Field(
        None, description="If generated from a recurring series, the series id"
    )
    recurrence_occurrence_start: Optional[datetime] = Field(
        None, description="If generated from a recurring series, the canonical occurrence start timestamp"
    )
    
    class Config:
        """Pydantic configuration."""
        use_enum_values = True

