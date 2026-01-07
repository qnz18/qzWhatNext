"""SQLAlchemy database models for qzWhatNext."""

from datetime import datetime
from typing import Optional, List
import uuid
from sqlalchemy import Column, String, Integer, Float, Boolean, DateTime, JSON

from qzwhatnext.database.database import Base
from qzwhatnext.models.task import TaskStatus, TaskCategory, EnergyIntensity


class TaskDB(Base):
    """Database model for Task."""
    
    __tablename__ = "tasks"
    
    # Primary key
    id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    
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
    
    # Scheduling fields
    deadline = Column(DateTime, nullable=True)
    estimated_duration_min = Column(Integer, nullable=False, default=30)
    duration_confidence = Column(Float, nullable=False, default=0.5)
    
    # Classification fields
    category = Column(String, nullable=False, default=TaskCategory.OTHER.value)
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
        
        return Task(
            id=self.id,
            source_type=self.source_type,
            source_id=self.source_id,
            title=self.title,
            notes=self.notes,
            status=TaskStatus(self.status),
            created_at=self.created_at,
            updated_at=self.updated_at,
            deadline=self.deadline,
            estimated_duration_min=self.estimated_duration_min,
            duration_confidence=self.duration_confidence,
            category=TaskCategory(self.category),
            energy_intensity=EnergyIntensity(self.energy_intensity),
            risk_score=self.risk_score,
            impact_score=self.impact_score,
            dependencies=self.dependencies or [],
            flexibility_window=flex_window,
            ai_excluded=self.ai_excluded,
            manual_priority_locked=self.manual_priority_locked,
            user_locked=self.user_locked,
            manually_scheduled=self.manually_scheduled,
        )
    
    @classmethod
    def from_pydantic(cls, task):
        """Create database model from Pydantic model."""
        # Convert flexibility_window to JSON
        flex_window = None
        if task.flexibility_window:
            flex_window = [d.isoformat() for d in task.flexibility_window]
        
        # Handle enum values (Pydantic with use_enum_values=True returns strings)
        status_value = task.status.value if hasattr(task.status, 'value') else task.status
        category_value = task.category.value if hasattr(task.category, 'value') else task.category
        energy_value = task.energy_intensity.value if hasattr(task.energy_intensity, 'value') else task.energy_intensity
        
        return cls(
            id=task.id,
            source_type=task.source_type,
            source_id=task.source_id,
            title=task.title,
            notes=task.notes,
            status=status_value,
            created_at=task.created_at,
            updated_at=task.updated_at,
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
        )

