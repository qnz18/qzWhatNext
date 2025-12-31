"""AuditEvent data model for qzWhatNext."""

from datetime import datetime
from enum import Enum
from typing import Optional, Dict, Any
from pydantic import BaseModel, Field


class AuditEventType(str, Enum):
    """Audit event type enumeration."""
    TASK_IMPORTED = "task_imported"
    TASK_UPDATED = "task_updated"
    ATTRIBUTE_INFERRED = "attribute_inferred"
    TIER_CHANGED = "tier_changed"
    SCHEDULE_BUILT = "schedule_built"
    SCHEDULE_UPDATED = "schedule_updated"
    SNOOZED = "snoozed"
    RESCHEDULED = "rescheduled"
    COMPLETED = "completed"
    OVERFLOW_FLAGGED = "overflow_flagged"


class AuditEvent(BaseModel):
    """Audit event captures trust-critical behavior."""
    
    id: str = Field(..., description="Unique audit event identifier")
    timestamp: datetime = Field(default_factory=datetime.utcnow, description="Event timestamp")
    event_type: AuditEventType = Field(..., description="Type of audit event")
    entity_id: str = Field(..., description="ID of the entity this event relates to")
    details: Dict[str, Any] = Field(default_factory=dict, description="Additional event details")
    
    class Config:
        """Pydantic configuration."""
        use_enum_values = True

