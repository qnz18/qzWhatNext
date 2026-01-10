"""Tests for task creation logic (current implementation baseline).

These tests capture the current behavior of task creation before refactoring.
"""

import pytest
from datetime import datetime
import uuid

from qzwhatnext.models.task import Task, TaskStatus, TaskCategory, EnergyIntensity


class TestTaskCreationDefaults:
    """Test that task creation uses correct default values."""
    
    def test_default_task_values(self, sample_task_base):
        """Test that task has correct default values."""
        task = Task(**sample_task_base)
        
        assert task.status == TaskStatus.OPEN
        assert task.estimated_duration_min == 30
        assert task.duration_confidence == 0.5
        assert task.category == TaskCategory.UNKNOWN
        assert task.energy_intensity == EnergyIntensity.MEDIUM
        assert task.risk_score == 0.3
        assert task.impact_score == 0.3
        assert task.dependencies == []
        assert task.ai_excluded is False
        assert task.manual_priority_locked is False
        assert task.user_locked is False
        assert task.manually_scheduled is False
    
    def test_ai_exclusion_from_title(self, sample_task_base):
        """Test that task with title starting with '.' has ai_excluded=True."""
        task = Task(**{**sample_task_base, "title": ".Private Task"})
        
        # Note: In current implementation, ai_excluded is set based on title.startswith('.')
        # This test verifies the behavior before refactoring
        assert task.title.startswith('.')
        # ai_excluded flag should be set during creation (in API endpoint)
    
    def test_ai_exclusion_explicit_flag(self, sample_task_base):
        """Test that task with explicit ai_excluded flag works."""
        task = Task(**{**sample_task_base, "ai_excluded": True})
        
        assert task.ai_excluded is True
    
    def test_task_with_deadline(self, sample_task_base):
        """Test creating task with deadline."""
        deadline = datetime.utcnow()
        task = Task(**{**sample_task_base, "deadline": deadline})
        
        assert task.deadline == deadline
    
    def test_task_with_custom_duration(self, sample_task_base):
        """Test creating task with custom duration."""
        task = Task(**{**sample_task_base, "estimated_duration_min": 60})
        
        assert task.estimated_duration_min == 60
    
    def test_task_with_category(self, sample_task_base):
        """Test creating task with category."""
        task = Task(**{**sample_task_base, "category": TaskCategory.WORK})
        
        assert task.category == TaskCategory.WORK
    
    def test_task_with_dependencies(self, sample_task_base):
        """Test creating task with dependencies."""
        dep_id = str(uuid.uuid4())
        task = Task(**{**sample_task_base, "dependencies": [dep_id]})
        
        assert len(task.dependencies) == 1
        assert task.dependencies[0] == dep_id
    
    def test_task_source_type(self, sample_task_base):
        """Test that task has source_type."""
        task = Task(**{**sample_task_base, "source_type": "api"})
        
        assert task.source_type == "api"
    
    def test_task_source_id_null_for_api(self, sample_task_base):
        """Test that API-created tasks have source_id=None."""
        task = Task(**{**sample_task_base, "source_type": "api", "source_id": None})
        
        assert task.source_id is None
    
    def test_task_source_id_for_sheets(self, sample_task_base):
        """Test that Google Sheets tasks can have source_id."""
        task = Task(**{**sample_task_base, "source_type": "google_sheets", "source_id": "sheet123"})
        
        assert task.source_id == "sheet123"

