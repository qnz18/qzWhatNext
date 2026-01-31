"""SQLAlchemy database models for qzWhatNext."""

from datetime import datetime
from typing import Optional, List
import uuid
from sqlalchemy import Column, String, Integer, Float, Boolean, DateTime, JSON, ForeignKey, UniqueConstraint

from typing import Union, TypeVar, Type
from qzwhatnext.database.database import Base
from qzwhatnext.models.task import TaskStatus, TaskCategory, EnergyIntensity
from qzwhatnext.models.scheduled_block import EntityType, ScheduledBy

T = TypeVar('T')


def enum_to_value(enum_obj: Union[str, T]) -> str:
    """Convert enum to string value (handles both enum and string).
    
    Args:
        enum_obj: Enum instance or string value
        
    Returns:
        String value of the enum, or the string itself if already a string
    """
    if hasattr(enum_obj, 'value'):
        return enum_obj.value
    return str(enum_obj)


def value_to_enum(value: str, enum_class: Type[T], default: T) -> T:
    """Convert string to enum with fallback to default.
    
    Args:
        value: String value to convert
        enum_class: Enum class to convert to
        default: Default enum value if conversion fails
        
    Returns:
        Enum instance, or default if conversion fails
    """
    if not value:
        return default
    try:
        return enum_class(value.lower())
    except (ValueError, AttributeError):
        return default


class TaskDB(Base):
    """Database model for Task."""
    
    __tablename__ = "tasks"
    __table_args__ = (
        # Prevent duplicate generation of the same recurring occurrence for a series.
        # Note: NULL values do not participate (non-recurring tasks are unaffected).
        UniqueConstraint("user_id", "recurrence_series_id", "recurrence_occurrence_start", name="uq_task_recurrence_occurrence"),
    )
    
    # Primary key
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    
    # User association
    user_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    
    # Source metadata
    source_type = Column(String, nullable=False, index=True)
    source_id = Column(String, nullable=True, index=True)
    
    # Basic fields
    title = Column(String, nullable=False)
    notes = Column(String, nullable=True)
    status = Column(String, nullable=False, default=TaskStatus.OPEN.value)
    
    # Timestamps
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    deleted_at = Column(DateTime, nullable=True, index=True)
    
    # Scheduling fields
    deadline = Column(DateTime, nullable=True)
    estimated_duration_min = Column(Integer, nullable=False, default=30)
    duration_confidence = Column(Float, nullable=False, default=0.5)
    
    # Classification fields
    category = Column(String, nullable=False, default=TaskCategory.UNKNOWN.value)
    energy_intensity = Column(String, nullable=False, default=EnergyIntensity.MEDIUM.value)
    risk_score = Column(Float, nullable=False, default=0.3)
    impact_score = Column(Float, nullable=False, default=0.3)
    
    # Dependencies (stored as JSON array)
    dependencies = Column(JSON, nullable=False, default=list)
    
    # Flexibility window (stored as JSON tuple [earliest_start, latest_end])
    flexibility_window = Column(JSON, nullable=True)
    
    # Flags
    ai_excluded = Column(Boolean, nullable=False, default=False)
    manual_priority_locked = Column(Boolean, nullable=False, default=False)
    user_locked = Column(Boolean, nullable=False, default=False)
    manually_scheduled = Column(Boolean, nullable=False, default=False)

    # Recurrence linkage (optional)
    recurrence_series_id = Column(String, ForeignKey("recurring_task_series.id", ondelete="SET NULL"), nullable=True, index=True)
    recurrence_occurrence_start = Column(DateTime, nullable=True, index=True)
    
    def to_pydantic(self):
        """Convert database model to Pydantic model."""
        from qzwhatnext.models.task import Task
        
        # Convert flexibility_window from JSON
        flex_window = None
        if self.flexibility_window:
            # Handle both list and tuple formats
            if isinstance(self.flexibility_window, list) and len(self.flexibility_window) == 2:
                flex_window = (
                    datetime.fromisoformat(self.flexibility_window[0]) if isinstance(self.flexibility_window[0], str) else self.flexibility_window[0],
                    datetime.fromisoformat(self.flexibility_window[1]) if isinstance(self.flexibility_window[1], str) else self.flexibility_window[1]
                )
        
        # Handle legacy category values (migration support)
        category_mapping = {
            'social': TaskCategory.FAMILY,
            'stress': TaskCategory.PERSONAL,
            'other': TaskCategory.UNKNOWN,
        }
        category = category_mapping.get(self.category.lower(), None)
        if category is None:
            category = value_to_enum(self.category, TaskCategory, TaskCategory.UNKNOWN)
        
        return Task(
            id=self.id,
            user_id=self.user_id,
            source_type=self.source_type,
            source_id=self.source_id,
            title=self.title,
            notes=self.notes,
            status=value_to_enum(self.status, TaskStatus, TaskStatus.OPEN),
            created_at=self.created_at,
            updated_at=self.updated_at,
            deleted_at=self.deleted_at,
            deadline=self.deadline,
            estimated_duration_min=self.estimated_duration_min,
            duration_confidence=self.duration_confidence,
            category=category,
            energy_intensity=value_to_enum(self.energy_intensity, EnergyIntensity, EnergyIntensity.MEDIUM),
            risk_score=self.risk_score,
            impact_score=self.impact_score,
            dependencies=self.dependencies or [],
            flexibility_window=flex_window,
            ai_excluded=self.ai_excluded,
            manual_priority_locked=self.manual_priority_locked,
            user_locked=self.user_locked,
            manually_scheduled=self.manually_scheduled,
            recurrence_series_id=getattr(self, "recurrence_series_id", None),
            recurrence_occurrence_start=getattr(self, "recurrence_occurrence_start", None),
        )
    
    @classmethod
    def from_pydantic(cls, task):
        """Create database model from Pydantic model."""
        # Convert flexibility_window to JSON
        flex_window = None
        if task.flexibility_window:
            flex_window = [d.isoformat() for d in task.flexibility_window]
        
        # Handle enum values (Pydantic with use_enum_values=True returns strings)
        status_value = enum_to_value(task.status)
        category_value = enum_to_value(task.category)
        energy_value = enum_to_value(task.energy_intensity)
        
        return cls(
            id=task.id,
            user_id=task.user_id,
            source_type=task.source_type,
            source_id=task.source_id,
            title=task.title,
            notes=task.notes,
            status=status_value,
            created_at=task.created_at,
            updated_at=task.updated_at,
            deleted_at=task.deleted_at,
            deadline=task.deadline,
            estimated_duration_min=task.estimated_duration_min,
            duration_confidence=task.duration_confidence,
            category=category_value,
            energy_intensity=energy_value,
            risk_score=task.risk_score,
            impact_score=task.impact_score,
            dependencies=task.dependencies,
            flexibility_window=flex_window,
            ai_excluded=task.ai_excluded,
            manual_priority_locked=task.manual_priority_locked,
            user_locked=task.user_locked,
            manually_scheduled=task.manually_scheduled,
            recurrence_series_id=getattr(task, "recurrence_series_id", None),
            recurrence_occurrence_start=getattr(task, "recurrence_occurrence_start", None),
        )


class RecurringTaskSeriesDB(Base):
    """Database model for a recurring task series (template + recurrence preset)."""

    __tablename__ = "recurring_task_series"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)

    title_template = Column(String, nullable=False)
    notes_template = Column(String, nullable=True)

    estimated_duration_min_default = Column(Integer, nullable=False, default=30)
    category_default = Column(String, nullable=False, default=TaskCategory.UNKNOWN.value)

    recurrence_preset = Column(JSON, nullable=False)
    ai_excluded = Column(Boolean, nullable=False, default=False)

    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    deleted_at = Column(DateTime, nullable=True, index=True)


class RecurringTimeBlockDB(Base):
    """Database model for a recurring calendar/time block managed by qzWhatNext."""

    __tablename__ = "recurring_time_blocks"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)

    title = Column(String, nullable=False)
    recurrence_preset = Column(JSON, nullable=False)

    # Google Calendar event id for the recurring series "master" event.
    calendar_event_id = Column(String, nullable=True, index=True)

    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    deleted_at = Column(DateTime, nullable=True, index=True)


class UserDB(Base):
    """Database model for User."""
    
    __tablename__ = "users"
    
    # Primary key (Google user ID)
    id = Column(String, primary_key=True)
    
    # User profile
    email = Column(String, nullable=False, unique=True)
    name = Column(String, nullable=True)
    
    # Timestamps
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    def to_pydantic(self):
        """Convert database model to Pydantic model."""
        from qzwhatnext.models.user import User
        return User(
            id=self.id,
            email=self.email,
            name=self.name,
            created_at=self.created_at,
            updated_at=self.updated_at,
        )
    
    @classmethod
    def from_pydantic(cls, user):
        """Create database model from Pydantic model."""
        return cls(
            id=user.id,
            email=user.email,
            name=user.name,
            created_at=user.created_at,
            updated_at=user.updated_at,
        )


class ScheduledBlockDB(Base):
    """Database model for ScheduledBlock."""
    
    __tablename__ = "scheduled_blocks"
    
    # Primary key
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    
    # User association
    user_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    
    # Block details
    entity_type = Column(String, nullable=False)
    entity_id = Column(String, nullable=False)
    start_time = Column(DateTime, nullable=False)
    end_time = Column(DateTime, nullable=False)
    scheduled_by = Column(String, nullable=False)
    locked = Column(Boolean, nullable=False, default=False)
    calendar_event_id = Column(String, nullable=True)
    calendar_event_etag = Column(String, nullable=True)
    calendar_event_updated_at = Column(DateTime, nullable=True)
    
    # Timestamps
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    
    def to_pydantic(self):
        """Convert database model to Pydantic model."""
        from qzwhatnext.models.scheduled_block import ScheduledBlock, EntityType, ScheduledBy
        return ScheduledBlock(
            id=self.id,
            user_id=self.user_id,
            entity_type=value_to_enum(self.entity_type, EntityType, EntityType.TASK),
            entity_id=self.entity_id,
            start_time=self.start_time,
            end_time=self.end_time,
            scheduled_by=value_to_enum(self.scheduled_by, ScheduledBy, ScheduledBy.SYSTEM),
            locked=self.locked,
            calendar_event_id=self.calendar_event_id,
            calendar_event_etag=self.calendar_event_etag,
            calendar_event_updated_at=self.calendar_event_updated_at,
        )
    
    @classmethod
    def from_pydantic(cls, block):
        """Create database model from Pydantic model."""
        return cls(
            id=block.id,
            user_id=block.user_id,
            entity_type=enum_to_value(block.entity_type),
            entity_id=block.entity_id,
            start_time=block.start_time,
            end_time=block.end_time,
            scheduled_by=enum_to_value(block.scheduled_by),
            locked=block.locked,
            calendar_event_id=block.calendar_event_id,
            calendar_event_etag=getattr(block, "calendar_event_etag", None),
            calendar_event_updated_at=getattr(block, "calendar_event_updated_at", None),
        )


class ApiTokenDB(Base):
    """Long-lived API tokens for automation (e.g., iOS Shortcuts).

    We store only a hash of the token, never the raw token.
    """

    __tablename__ = "api_tokens"

    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    user_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)

    # HMAC-SHA256 hex digest of the token
    token_hash = Column(String, nullable=False, unique=True, index=True)

    # Non-sensitive prefix for UI/debug (first few chars of raw token)
    token_prefix = Column(String, nullable=False, default="")

    name = Column(String, nullable=False, default="shortcut")

    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    last_used_at = Column(DateTime, nullable=True)
    revoked_at = Column(DateTime, nullable=True)


class GoogleOAuthTokenDB(Base):
    """Per-user OAuth tokens for Google integrations (e.g., Calendar).

    Tokens are stored encrypted-at-rest (see repository layer); do NOT log raw tokens.
    """

    __tablename__ = "google_oauth_tokens"

    # Composite primary key: one row per user/provider/product.
    user_id = Column(String, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    provider = Column(String, primary_key=True)  # e.g. "google"
    product = Column(String, primary_key=True)   # e.g. "calendar"

    scopes = Column(JSON, nullable=False, default=list)

    refresh_token_encrypted = Column(String, nullable=False)
    access_token_encrypted = Column(String, nullable=True)
    expiry = Column(DateTime, nullable=True)

    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

