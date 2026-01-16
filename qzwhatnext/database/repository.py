"""Repository layer for database operations."""

import logging
from typing import List, Optional
from sqlalchemy.orm import Session
from sqlalchemy import and_, desc

from qzwhatnext.models.task import Task
from qzwhatnext.database.models import TaskDB, enum_to_value

logger = logging.getLogger(__name__)


class TaskRepository:
    """Repository for Task database operations."""
    
    def __init__(self, db: Session):
        self.db = db
    
    def create(self, task: Task) -> Task:
        """Create a new task."""
        try:
            task_db = TaskDB.from_pydantic(task)
            self.db.add(task_db)
            self.db.commit()
            self.db.refresh(task_db)
            logger.debug(f"Created task {task.id}: {task.title[:50]}")
            return task_db.to_pydantic()
        except Exception as e:
            self.db.rollback()
            logger.error(f"Failed to create task {task.id}: {type(e).__name__}: {str(e)}")
            raise
    
    def get(self, user_id: str, task_id: str) -> Optional[Task]:
        """Get task by ID for a specific user."""
        task_db = self.db.query(TaskDB).filter(
            TaskDB.id == task_id,
            TaskDB.user_id == user_id
        ).first()
        return task_db.to_pydantic() if task_db else None
    
    def get_all(self, user_id: str) -> List[Task]:
        """Get all tasks for a user sorted by creation date (newest first)."""
        tasks_db = self.db.query(TaskDB).filter(
            TaskDB.user_id == user_id
        ).order_by(desc(TaskDB.created_at)).all()
        return [task_db.to_pydantic() for task_db in tasks_db]
    
    def get_open(self, user_id: str) -> List[Task]:
        """Get all open (non-completed) tasks for a user."""
        tasks_db = self.db.query(TaskDB).filter(
            TaskDB.user_id == user_id,
            TaskDB.status == "open"
        ).all()
        return [task_db.to_pydantic() for task_db in tasks_db]
    
    def update(self, task: Task) -> Task:
        """Update an existing task (user_id must match task.user_id)."""
        task_db = self.db.query(TaskDB).filter(
            TaskDB.id == task.id,
            TaskDB.user_id == task.user_id
        ).first()
        if not task_db:
            raise ValueError(f"Task {task.id} not found")
        
        # Handle enum values (Pydantic with use_enum_values=True returns strings)
        status_value = enum_to_value(task.status)
        category_value = enum_to_value(task.category)
        energy_value = enum_to_value(task.energy_intensity)
        
        # Update all fields
        task_db.source_type = task.source_type
        task_db.source_id = task.source_id
        task_db.title = task.title
        task_db.notes = task.notes
        task_db.status = status_value
        task_db.updated_at = task.updated_at
        task_db.deadline = task.deadline
        task_db.estimated_duration_min = task.estimated_duration_min
        task_db.duration_confidence = task.duration_confidence
        task_db.category = category_value
        task_db.energy_intensity = energy_value
        task_db.risk_score = task.risk_score
        task_db.impact_score = task.impact_score
        task_db.dependencies = task.dependencies
        task_db.flexibility_window = [d.isoformat() for d in task.flexibility_window] if task.flexibility_window else None
        task_db.ai_excluded = task.ai_excluded
        task_db.manual_priority_locked = task.manual_priority_locked
        task_db.user_locked = task.user_locked
        task_db.manually_scheduled = task.manually_scheduled
        
        try:
            self.db.commit()
            self.db.refresh(task_db)
            logger.debug(f"Updated task {task.id}: {task.title[:50]}")
            return task_db.to_pydantic()
        except Exception as e:
            self.db.rollback()
            logger.error(f"Failed to update task {task.id}: {type(e).__name__}: {str(e)}")
            raise
    
    def delete(self, user_id: str, task_id: str) -> bool:
        """Delete a task by ID for a specific user."""
        task_db = self.db.query(TaskDB).filter(
            TaskDB.id == task_id,
            TaskDB.user_id == user_id
        ).first()
        if not task_db:
            return False
        
        try:
            self.db.delete(task_db)
            self.db.commit()
            logger.debug(f"Deleted task {task_id}")
            return True
        except Exception as e:
            self.db.rollback()
            logger.error(f"Failed to delete task {task_id}: {type(e).__name__}: {str(e)}")
            raise
    
    def find_duplicates(self, user_id: str, source_type: str, source_id: Optional[str], title: str) -> List[Task]:
        """Find potential duplicate tasks (matching user_id, source_type, source_id, title)."""
        conditions = [
            TaskDB.user_id == user_id,
            TaskDB.source_type == source_type,
            TaskDB.title == title
        ]
        if source_id:
            conditions.append(TaskDB.source_id == source_id)
        
        tasks_db = self.db.query(TaskDB).filter(and_(*conditions)).all()
        return [task_db.to_pydantic() for task_db in tasks_db]

