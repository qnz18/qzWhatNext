"""Tests for TaskRepository CRUD operations."""

import pytest
from datetime import datetime, timedelta
import uuid

from qzwhatnext.database.repository import TaskRepository
from qzwhatnext.models.task import Task, TaskStatus, TaskCategory, EnergyIntensity


class TestTaskRepository:
    """Test TaskRepository CRUD operations."""
    
    def test_create_task(self, task_repository, sample_task, test_user_id):
        """Test creating a task."""
        created = task_repository.create(sample_task)
        
        assert created.id == sample_task.id
        assert created.title == sample_task.title
        assert created.status == sample_task.status
        assert created.user_id == test_user_id
    
    def test_get_task_by_id(self, task_repository, sample_task, test_user_id):
        """Test retrieving a task by ID."""
        created = task_repository.create(sample_task)
        retrieved = task_repository.get(test_user_id, created.id)
        
        assert retrieved is not None
        assert retrieved.id == created.id
        assert retrieved.title == created.title
    
    def test_get_nonexistent_task(self, task_repository, test_user_id):
        """Test retrieving a nonexistent task returns None."""
        result = task_repository.get(test_user_id, "nonexistent-id")
        assert result is None
    
    def test_get_all_tasks(self, task_repository, sample_task_base, test_user_id):
        """Test retrieving all tasks."""
        task1 = Task(**{**sample_task_base, "id": str(uuid.uuid4()), "title": "Task 1"})
        task2 = Task(**{**sample_task_base, "id": str(uuid.uuid4()), "title": "Task 2"})
        task3 = Task(**{**sample_task_base, "id": str(uuid.uuid4()), "title": "Task 3"})
        
        task_repository.create(task1)
        task_repository.create(task2)
        task_repository.create(task3)
        
        all_tasks = task_repository.get_all(test_user_id)
        assert len(all_tasks) == 3
        assert all(task.title in ["Task 1", "Task 2", "Task 3"] for task in all_tasks)
    
    def test_get_all_sorted_by_creation_date(self, task_repository, sample_task_base, test_user_id):
        """Test that get_all() returns tasks sorted by creation date (newest first)."""
        now = datetime.utcnow()
        task1 = Task(**{**sample_task_base, "id": str(uuid.uuid4()), "created_at": now, "title": "Task 1"})
        task2 = Task(**{**sample_task_base, "id": str(uuid.uuid4()), "created_at": now - timedelta(minutes=1), "title": "Task 2"})
        task3 = Task(**{**sample_task_base, "id": str(uuid.uuid4()), "created_at": now - timedelta(minutes=2), "title": "Task 3"})
        
        # Create in reverse order
        task_repository.create(task3)
        task_repository.create(task2)
        task_repository.create(task1)
        
        all_tasks = task_repository.get_all(test_user_id)
        # Should be sorted newest first
        assert all_tasks[0].title == "Task 1"
        assert all_tasks[1].title == "Task 2"
        assert all_tasks[2].title == "Task 3"
    
    def test_get_open_tasks_only(self, task_repository, sample_task_base, test_user_id):
        """Test that get_open() returns only open tasks."""
        open_task = Task(**{**sample_task_base, "id": str(uuid.uuid4()), "title": "Open Task", "status": TaskStatus.OPEN})
        completed_task = Task(**{**sample_task_base, "id": str(uuid.uuid4()), "title": "Completed Task", "status": TaskStatus.COMPLETED})
        
        task_repository.create(open_task)
        task_repository.create(completed_task)
        
        open_tasks = task_repository.get_open(test_user_id)
        assert len(open_tasks) == 1
        assert open_tasks[0].title == "Open Task"
        assert open_tasks[0].status == TaskStatus.OPEN

    def test_get_open_excludes_missed(self, task_repository, sample_task_base, test_user_id):
        """Test that get_open() excludes missed tasks (habit roll-forward)."""
        open_task = Task(**{**sample_task_base, "id": str(uuid.uuid4()), "title": "Open Task", "status": TaskStatus.OPEN})
        missed_task = Task(**{**sample_task_base, "id": str(uuid.uuid4()), "title": "Missed Task", "status": TaskStatus.MISSED})
        task_repository.create(open_task)
        task_repository.create(missed_task)
        open_tasks = task_repository.get_open(test_user_id)
        assert len(open_tasks) == 1
        assert open_tasks[0].status == TaskStatus.OPEN
    
    def test_update_task(self, task_repository, sample_task):
        """Test updating a task."""
        created = task_repository.create(sample_task)
        
        # Update task
        created.title = "Updated Title"
        created.notes = "Updated Notes"
        created.category = TaskCategory.WORK
        created.updated_at = datetime.utcnow()
        
        updated = task_repository.update(created)
        
        assert updated.title == "Updated Title"
        assert updated.notes == "Updated Notes"
        assert updated.category == TaskCategory.WORK
    
    def test_update_nonexistent_task_raises_error(self, task_repository, sample_task):
        """Test updating a nonexistent task raises ValueError."""
        sample_task.id = "nonexistent-id"
        
        with pytest.raises(ValueError, match="Task.*not found"):
            task_repository.update(sample_task)
    
    def test_delete_task(self, task_repository, sample_task, test_user_id):
        """Test deleting a task."""
        created = task_repository.create(sample_task)
        task_id = created.id
        
        result = task_repository.delete(test_user_id, task_id)
        assert result is True
        
        # Verify task is deleted
        retrieved = task_repository.get(test_user_id, task_id)
        assert retrieved is None

    def test_restore_task(self, task_repository, sample_task, test_user_id):
        """Test restoring a soft-deleted task."""
        created = task_repository.create(sample_task)
        task_id = created.id

        assert task_repository.delete(test_user_id, task_id) is True
        assert task_repository.get(test_user_id, task_id) is None

        assert task_repository.restore(test_user_id, task_id) is True
        restored = task_repository.get(test_user_id, task_id)
        assert restored is not None
        assert restored.id == task_id

    def test_purge_task(self, task_repository, sample_task, test_user_id):
        """Test permanently deleting a task."""
        created = task_repository.create(sample_task)
        task_id = created.id

        assert task_repository.purge(test_user_id, task_id) is True
        assert task_repository.get(test_user_id, task_id) is None
        assert task_repository.restore(test_user_id, task_id) is False

    def test_bulk_delete_restore_and_purge(self, task_repository, sample_task_base, test_user_id):
        """Test bulk soft-delete/restore/purge methods."""
        ids = []
        for title in ["Bulk 1", "Bulk 2", "Bulk 3"]:
            task = Task(**{**sample_task_base, "id": str(uuid.uuid4()), "title": title})
            created = task_repository.create(task)
            ids.append(created.id)

        nonexistent_id = "nonexistent-id"

        result = task_repository.bulk_delete(test_user_id, [ids[0], ids[1], nonexistent_id])
        assert result["affected_count"] == 2
        assert nonexistent_id in result["not_found_ids"]
        assert task_repository.get(test_user_id, ids[0]) is None
        assert task_repository.get(test_user_id, ids[1]) is None
        assert task_repository.get(test_user_id, ids[2]) is not None

        result = task_repository.bulk_restore(test_user_id, [ids[0], ids[1]])
        assert result["affected_count"] == 2
        assert task_repository.get(test_user_id, ids[0]) is not None
        assert task_repository.get(test_user_id, ids[1]) is not None

        result = task_repository.bulk_purge(test_user_id, [ids[0], ids[2], nonexistent_id])
        assert result["affected_count"] == 2
        assert task_repository.get(test_user_id, ids[0]) is None
        assert task_repository.get(test_user_id, ids[2]) is None
    
    def test_delete_nonexistent_task(self, task_repository, test_user_id):
        """Test deleting a nonexistent task returns False."""
        result = task_repository.delete(test_user_id, "nonexistent-id")
        assert result is False
    
    def test_find_duplicates_by_title(self, task_repository, sample_task_base, test_user_id):
        """Test finding duplicate tasks by title and source_type."""
        task1 = Task(**{**sample_task_base, "id": str(uuid.uuid4()), "source_type": "api", "title": "Duplicate Title"})
        task2 = Task(**{**sample_task_base, "id": str(uuid.uuid4()), "source_type": "api", "title": "Duplicate Title"})
        task3 = Task(**{**sample_task_base, "id": str(uuid.uuid4()), "source_type": "google_sheets", "title": "Duplicate Title"})
        
        task_repository.create(task1)
        task_repository.create(task2)
        task_repository.create(task3)
        
        # Find duplicates for source_type="api", title="Duplicate Title"
        duplicates = task_repository.find_duplicates(test_user_id, "api", None, "Duplicate Title")
        assert len(duplicates) == 2
        assert all(dup.source_type == "api" and dup.title == "Duplicate Title" for dup in duplicates)
    
    def test_find_duplicates_by_source_id(self, task_repository, sample_task_base, test_user_id):
        """Test finding duplicate tasks by source_id."""
        task1 = Task(**{**sample_task_base, "id": str(uuid.uuid4()), "source_type": "google_sheets", "source_id": "sheet123", "title": "Task"})
        task2 = Task(**{**sample_task_base, "id": str(uuid.uuid4()), "source_type": "google_sheets", "source_id": "sheet123", "title": "Task"})
        
        task_repository.create(task1)
        task_repository.create(task2)
        
        duplicates = task_repository.find_duplicates(test_user_id, "google_sheets", "sheet123", "Task")
        assert len(duplicates) == 2
        assert all(dup.source_id == "sheet123" for dup in duplicates)
    
    def test_no_duplicates_found(self, task_repository, sample_task_base, test_user_id):
        """Test that find_duplicates returns empty list when no duplicates exist."""
        task = Task(**{**sample_task_base, "id": str(uuid.uuid4()), "source_type": "api", "title": "Unique Title"})
        task_repository.create(task)
        
        duplicates = task_repository.find_duplicates(test_user_id, "api", None, "Different Title")
        assert len(duplicates) == 0

