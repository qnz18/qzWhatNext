"""Tests for AI exclusion enforcement (trust-critical).

These tests verify that AI-excluded tasks are never sent to AI and never receive AI-updated attributes.
This is a trust-critical component and must be checked BEFORE any AI calls.
"""

import pytest
from datetime import datetime
import uuid

from qzwhatnext.engine.ai_exclusion import is_ai_excluded, filter_ai_excluded
from qzwhatnext.models.task import Task, TaskStatus, TaskCategory, EnergyIntensity


class TestIsAIExcluded:
    """Test is_ai_excluded() function."""
    
    def test_task_with_period_prefix_title_is_excluded(self, sample_task_base):
        """Task with title starting with '.' should be excluded."""
        task = Task(**{**sample_task_base, "title": ".Private task"})
        assert is_ai_excluded(task) is True
    
    def test_task_with_period_prefix_notes_is_excluded(self, sample_task_base):
        """Task with notes starting with '.' should be excluded (for add_smart endpoint)."""
        task = Task(**{**sample_task_base, "title": "Task", "notes": ".Private notes"})
        assert is_ai_excluded(task) is True
    
    def test_task_with_explicit_ai_excluded_flag_is_excluded(self, sample_task_base):
        """Task with ai_excluded=True should be excluded."""
        task = Task(**{**sample_task_base, "ai_excluded": True})
        assert is_ai_excluded(task) is True
    
    def test_normal_task_is_not_excluded(self, sample_task):
        """Normal task without exclusion markers should not be excluded."""
        assert is_ai_excluded(sample_task) is False
    
    def test_task_with_empty_title_not_excluded(self, sample_task_base):
        """Task with empty title (not period prefix) should not be excluded."""
        task = Task(**{**sample_task_base, "title": ""})
        assert is_ai_excluded(task) is False
    
    def test_task_with_period_in_middle_not_excluded(self, sample_task_base):
        """Task with period in middle of title should not be excluded."""
        task = Task(**{**sample_task_base, "title": "Task.Private"})
        assert is_ai_excluded(task) is False
    
    def test_task_with_multiple_periods_at_start_is_excluded(self, sample_task_base):
        """Task with multiple periods at start should be excluded."""
        task = Task(**{**sample_task_base, "title": "..Very private"})
        assert is_ai_excluded(task) is True
    
    def test_task_with_period_and_space_is_excluded(self, sample_task_base):
        """Task with period followed by space should be excluded."""
        task = Task(**{**sample_task_base, "title": ". Private task"})
        assert is_ai_excluded(task) is True
    
    def test_task_with_explicit_flag_and_period_prefix_both_excluded(self, sample_task_base):
        """Task with both period prefix and explicit flag should be excluded."""
        task = Task(**{**sample_task_base, "title": ".Private", "ai_excluded": True})
        assert is_ai_excluded(task) is True


class TestFilterAIExcluded:
    """Test filter_ai_excluded() function."""
    
    def test_separates_excluded_and_allowed_tasks(self, sample_task_base):
        """Should separate tasks into excluded and allowed lists."""
        task1 = Task(**{**sample_task_base, "id": str(uuid.uuid4()), "title": "Normal Task"})
        task2 = Task(**{**sample_task_base, "id": str(uuid.uuid4()), "title": ".Private Task"})
        task3 = Task(**{**sample_task_base, "id": str(uuid.uuid4()), "title": "Another Normal", "ai_excluded": True})
        task4 = Task(**{**sample_task_base, "id": str(uuid.uuid4()), "title": "Public Task"})
        
        tasks = [task1, task2, task3, task4]
        ai_allowed, ai_excluded = filter_ai_excluded(tasks)
        
        assert len(ai_allowed) == 2
        assert len(ai_excluded) == 2
        assert task1 in ai_allowed
        assert task4 in ai_allowed
        assert task2 in ai_excluded
        assert task3 in ai_excluded
    
    def test_all_excluded_returns_empty_allowed_list(self, sample_task_base):
        """If all tasks are excluded, allowed list should be empty."""
        task1 = Task(**{**sample_task_base, "id": str(uuid.uuid4()), "title": ".Task1"})
        task2 = Task(**{**sample_task_base, "id": str(uuid.uuid4()), "title": ".Task2", "ai_excluded": True})
        
        tasks = [task1, task2]
        ai_allowed, ai_excluded = filter_ai_excluded(tasks)
        
        assert len(ai_allowed) == 0
        assert len(ai_excluded) == 2
    
    def test_all_allowed_returns_empty_excluded_list(self, sample_task_base):
        """If no tasks are excluded, excluded list should be empty."""
        task1 = Task(**{**sample_task_base, "id": str(uuid.uuid4()), "title": "Task1"})
        task2 = Task(**{**sample_task_base, "id": str(uuid.uuid4()), "title": "Task2"})
        
        tasks = [task1, task2]
        ai_allowed, ai_excluded = filter_ai_excluded(tasks)
        
        assert len(ai_allowed) == 2
        assert len(ai_excluded) == 0
    
    def test_empty_list_returns_two_empty_lists(self):
        """Empty input should return two empty lists."""
        ai_allowed, ai_excluded = filter_ai_excluded([])
        
        assert len(ai_allowed) == 0
        assert len(ai_excluded) == 0

