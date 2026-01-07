"""Repository layer for database operations."""

from typing import List, Optional
from sqlalchemy.orm import Session
from sqlalchemy import and_

from qzwhatnext.models.task import Task
from qzwhatnext.database.models import TaskDB


class TaskRepository:
    """Repository for Task database operations."""
    
    def __init__(self, db: Session):
        self.db = db
    
    def create(self, task: Task) -> Task:
        """Create a new task."""
        task_db = TaskDB.from_pydantic(task)
        self.db.add(task_db)
        self.db.commit()
        self.db.refresh(task_db)
        return task_db.to_pydantic()
    
    def get(self, task_id: str) -> Optional[Task]:
        """Get task by ID."""
        task_db = self.db.query(TaskDB).filter(TaskDB.id == task_id).first()
        return task_db.to_pydantic() if task_db else None
    
    def get_all(self) -> List[Task]:
        """Get all tasks."""
        tasks_db = self.db.query(TaskDB).all()
        return [task_db.to_pydantic() for task_db in tasks_db]
    
    def get_open(self) -> List[Task]:
        """Get all open (non-completed) tasks."""
        tasks_db = self.db.query(TaskDB).filter(TaskDB.status == "open").all()
        return [task_db.to_pydantic() for task_db in tasks_db]
    
    def update(self, task: Task) -> Task:
        """Update an existing task."""
        task_db = self.db.query(TaskDB).filter(TaskDB.id == task.id).first()
        if not task_db:
            raise ValueError(f"Task {task.id} not found")
        
        # Handle enum values (Pydantic with use_enum_values=True returns strings)
        status_value = task.status.value if hasattr(task.status, 'value') else task.status
        category_value = task.category.value if hasattr(task.category, 'value') else task.category
        energy_value = task.energy_intensity.value if hasattr(task.energy_intensity, 'value') else task.energy_intensity
        
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
        
        self.db.commit()
        self.db.refresh(task_db)
        return task_db.to_pydantic()
    
    def delete(self, task_id: str) -> bool:
        """Delete a task by ID."""
        task_db = self.db.query(TaskDB).filter(TaskDB.id == task_id).first()
        if not task_db:
            return False
        
        self.db.delete(task_db)
        self.db.commit()
        return True
    
    def find_duplicates(self, source_type: str, source_id: Optional[str], title: str) -> List[Task]:
        """Find potential duplicate tasks (matching source_type, source_id, title)."""
        conditions = [
            TaskDB.source_type == source_type,
            TaskDB.title == title
        ]
        if source_id:
            conditions.append(TaskDB.source_id == source_id)
        
        tasks_db = self.db.query(TaskDB).filter(and_(*conditions)).all()
        return [task_db.to_pydantic() for task_db in tasks_db]

