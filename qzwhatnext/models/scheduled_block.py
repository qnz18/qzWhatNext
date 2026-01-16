"""ScheduledBlock data model for qzWhatNext."""

from datetime import datetime
from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field


class EntityType(str, Enum):
    """Entity type enumeration."""
    TASK = "task"
    TRANSITION = "transition"


class ScheduledBy(str, Enum):
    """Who scheduled this block."""
    SYSTEM = "system"
    USER = "user"


class ScheduledBlock(BaseModel):
    """ScheduledBlock represents something placed on the calendar."""
    
    id: str = Field(..., description="Unique scheduled block identifier")
    user_id: str = Field(..., description="User ID who owns this scheduled block")
    entity_type: EntityType = Field(..., description="Type of entity (task or transition)")
    entity_id: str = Field(..., description="ID of the entity being scheduled")
    start_time: datetime = Field(..., description="Block start time")
    end_time: datetime = Field(..., description="Block end time")
    scheduled_by: ScheduledBy = Field(ScheduledBy.SYSTEM, description="Who scheduled this block")
    locked: bool = Field(False, description="Whether this block is locked from movement")
    calendar_event_id: Optional[str] = Field(None, description="Calendar event ID for sync (null if not synced)")
    
    class Config:
        """Pydantic configuration."""
        use_enum_values = True

