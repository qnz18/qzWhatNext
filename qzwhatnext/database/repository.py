"""Repository layer for database operations."""

import logging
from datetime import datetime
from typing import List, Optional, Dict, Set
from sqlalchemy.orm import Session
from sqlalchemy import and_, desc

from qzwhatnext.models.task import Task
from qzwhatnext.database.models import TaskDB, enum_to_value

logger = logging.getLogger(__name__)


class TaskRepository:
    """Repository for Task database operations."""
    
    def __init__(self, db: Session):
        self.db = db

    def _as_unique_ids(self, task_ids: List[str]) -> List[str]:
        """Deduplicate while preserving order."""
        seen: Set[str] = set()
        unique: List[str] = []
        for task_id in task_ids:
            if task_id not in seen:
                seen.add(task_id)
                unique.append(task_id)
        return unique
    
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
            TaskDB.user_id == user_id,
            TaskDB.deleted_at.is_(None),
        ).first()
        return task_db.to_pydantic() if task_db else None
    
    def get_all(self, user_id: str) -> List[Task]:
        """Get all tasks for a user sorted by creation date (newest first)."""
        tasks_db = self.db.query(TaskDB).filter(
            TaskDB.user_id == user_id,
            TaskDB.deleted_at.is_(None),
        ).order_by(desc(TaskDB.created_at)).all()
        return [task_db.to_pydantic() for task_db in tasks_db]
    
    def get_open(self, user_id: str) -> List[Task]:
        """Get all open (non-completed, non-missed) tasks for a user."""
        tasks_db = self.db.query(TaskDB).filter(
            TaskDB.user_id == user_id,
            TaskDB.status == "open",
            TaskDB.deleted_at.is_(None),
        ).all()
        return [task_db.to_pydantic() for task_db in tasks_db]

    def get_open_tasks_for_recurrence_series(self, user_id: str, recurrence_series_id: str) -> List[Task]:
        """Get open tasks that belong to a recurrence series (for habit: at most one expected)."""
        tasks_db = self.db.query(TaskDB).filter(
            TaskDB.user_id == user_id,
            TaskDB.recurrence_series_id == recurrence_series_id,
            TaskDB.status == "open",
            TaskDB.deleted_at.is_(None),
        ).all()
        return [task_db.to_pydantic() for task_db in tasks_db]

    def get_open_recurrence_tasks_with_window_before(self, user_id: str, before: datetime) -> List[Task]:
        """Open recurrence tasks whose flexibility_window end is before the given time (past window)."""
        tasks_db = self.db.query(TaskDB).filter(
            TaskDB.user_id == user_id,
            TaskDB.recurrence_series_id.isnot(None),
            TaskDB.status == "open",
            TaskDB.deleted_at.is_(None),
        ).all()
        out: List[Task] = []
        for t in tasks_db:
            p = t.to_pydantic()
            if p.flexibility_window and p.flexibility_window[1] < before:
                out.append(p)
        return out

    def update(self, task: Task) -> Task:
        """Update an existing task (user_id must match task.user_id)."""
        task_db = self.db.query(TaskDB).filter(
            TaskDB.id == task.id,
            TaskDB.user_id == task.user_id,
            TaskDB.deleted_at.is_(None),
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
        task_db.start_after = getattr(task, "start_after", None)
        task_db.due_by = getattr(task, "due_by", None)
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
        """Soft-delete a task by ID for a specific user."""
        task_db = self.db.query(TaskDB).filter(
            TaskDB.id == task_id,
            TaskDB.user_id == user_id,
            TaskDB.deleted_at.is_(None),
        ).first()
        if not task_db:
            return False
        
        try:
            task_db.deleted_at = datetime.utcnow()
            self.db.commit()
            logger.debug(f"Soft-deleted task {task_id}")
            return True
        except Exception as e:
            self.db.rollback()
            logger.error(f"Failed to soft-delete task {task_id}: {type(e).__name__}: {str(e)}")
            raise

    def restore(self, user_id: str, task_id: str) -> bool:
        """Restore a soft-deleted task by ID for a specific user."""
        task_db = self.db.query(TaskDB).filter(
            TaskDB.id == task_id,
            TaskDB.user_id == user_id,
        ).first()
        if not task_db:
            return False

        # Idempotent restore: if it's already active, treat as success
        if task_db.deleted_at is None:
            return True

        try:
            task_db.deleted_at = None
            self.db.commit()
            logger.debug(f"Restored task {task_id}")
            return True
        except Exception as e:
            self.db.rollback()
            logger.error(f"Failed to restore task {task_id}: {type(e).__name__}: {str(e)}")
            raise

    def purge(self, user_id: str, task_id: str) -> bool:
        """Permanently delete a task by ID for a specific user."""
        task_db = self.db.query(TaskDB).filter(
            TaskDB.id == task_id,
            TaskDB.user_id == user_id,
        ).first()
        if not task_db:
            return False

        try:
            self.db.delete(task_db)
            self.db.commit()
            logger.debug(f"Purged task {task_id}")
            return True
        except Exception as e:
            self.db.rollback()
            logger.error(f"Failed to purge task {task_id}: {type(e).__name__}: {str(e)}")
            raise

    def bulk_delete(self, user_id: str, task_ids: List[str]) -> Dict[str, object]:
        """Soft-delete multiple tasks for a user.

        Only active (non-deleted) tasks are soft-deleted. Already-deleted tasks are treated as not found.
        """
        unique_ids = self._as_unique_ids(task_ids)
        if not unique_ids:
            return {"affected_count": 0, "not_found_ids": []}

        active_ids = {
            row[0]
            for row in self.db.query(TaskDB.id).filter(
                TaskDB.user_id == user_id,
                TaskDB.id.in_(unique_ids),
                TaskDB.deleted_at.is_(None),
            ).all()
        }
        not_found_ids = [task_id for task_id in unique_ids if task_id not in active_ids]

        try:
            affected = (
                self.db.query(TaskDB)
                .filter(
                    TaskDB.user_id == user_id,
                    TaskDB.id.in_(list(active_ids)),
                    TaskDB.deleted_at.is_(None),
                )
                .update({TaskDB.deleted_at: datetime.utcnow()}, synchronize_session=False)
            )
            self.db.commit()
            logger.debug(f"Soft-deleted {affected} tasks for user {user_id}")
            return {"affected_count": int(affected), "not_found_ids": not_found_ids}
        except Exception as e:
            self.db.rollback()
            logger.error(f"Failed to bulk soft-delete tasks for user {user_id}: {type(e).__name__}: {str(e)}")
            raise

    def bulk_restore(self, user_id: str, task_ids: List[str]) -> Dict[str, object]:
        """Restore multiple tasks for a user.

        Restores tasks that exist and are currently soft-deleted. Active tasks are left unchanged.
        """
        unique_ids = self._as_unique_ids(task_ids)
        if not unique_ids:
            return {"affected_count": 0, "not_found_ids": []}

        existing_ids = {
            row[0]
            for row in self.db.query(TaskDB.id).filter(
                TaskDB.user_id == user_id,
                TaskDB.id.in_(unique_ids),
            ).all()
        }
        not_found_ids = [task_id for task_id in unique_ids if task_id not in existing_ids]

        try:
            affected = (
                self.db.query(TaskDB)
                .filter(
                    TaskDB.user_id == user_id,
                    TaskDB.id.in_(list(existing_ids)),
                    TaskDB.deleted_at.is_not(None),
                )
                .update({TaskDB.deleted_at: None}, synchronize_session=False)
            )
            self.db.commit()
            logger.debug(f"Restored {affected} tasks for user {user_id}")
            return {"affected_count": int(affected), "not_found_ids": not_found_ids}
        except Exception as e:
            self.db.rollback()
            logger.error(f"Failed to bulk restore tasks for user {user_id}: {type(e).__name__}: {str(e)}")
            raise

    def bulk_purge(self, user_id: str, task_ids: List[str]) -> Dict[str, object]:
        """Permanently delete multiple tasks for a user."""
        unique_ids = self._as_unique_ids(task_ids)
        if not unique_ids:
            return {"affected_count": 0, "not_found_ids": []}

        existing_ids = {
            row[0]
            for row in self.db.query(TaskDB.id).filter(
                TaskDB.user_id == user_id,
                TaskDB.id.in_(unique_ids),
            ).all()
        }
        not_found_ids = [task_id for task_id in unique_ids if task_id not in existing_ids]

        try:
            affected = (
                self.db.query(TaskDB)
                .filter(
                    TaskDB.user_id == user_id,
                    TaskDB.id.in_(list(existing_ids)),
                )
                .delete(synchronize_session=False)
            )
            self.db.commit()
            logger.debug(f"Purged {affected} tasks for user {user_id}")
            return {"affected_count": int(affected), "not_found_ids": not_found_ids}
        except Exception as e:
            self.db.rollback()
            logger.error(f"Failed to bulk purge tasks for user {user_id}: {type(e).__name__}: {str(e)}")
            raise
    
    def find_duplicates(self, user_id: str, source_type: str, source_id: Optional[str], title: str) -> List[Task]:
        """Find potential duplicate tasks (matching user_id, source_type, source_id, title)."""
        conditions = [
            TaskDB.user_id == user_id,
            TaskDB.source_type == source_type,
            TaskDB.title == title,
            TaskDB.deleted_at.is_(None),
        ]
        if source_id:
            conditions.append(TaskDB.source_id == source_id)
        
        tasks_db = self.db.query(TaskDB).filter(and_(*conditions)).all()
        return [task_db.to_pydantic() for task_db in tasks_db]

