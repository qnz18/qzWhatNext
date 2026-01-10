"""Tests for scheduling algorithm (deterministic behavior).

These tests verify that scheduling is deterministic (same inputs → same outputs)
and handles overflow correctly.
"""

import pytest
from datetime import datetime, timedelta
import uuid

from qzwhatnext.engine.scheduler import schedule_tasks, SchedulingResult, SCHEDULING_GRANULARITY_MINUTES, round_to_granularity
from qzwhatnext.engine.ranking import stack_rank
from qzwhatnext.models.task import Task, TaskStatus, TaskCategory, EnergyIntensity
from qzwhatnext.models.scheduled_block import EntityType, ScheduledBy


class TestScheduleTasks:
    """Test schedule_tasks() function for deterministic behavior."""
    
    def test_schedules_single_task(self, sample_task_base):
        """Test scheduling a single task."""
        task = Task(**{**sample_task_base, "estimated_duration_min": 30})
        start_time = datetime(2024, 1, 1, 10, 0, 0)
        end_time = start_time + timedelta(days=7)
        
        result = schedule_tasks([task], start_time=start_time, end_time=end_time)
        
        assert len(result.scheduled_blocks) == 1
        assert len(result.overflow_tasks) == 0
        assert result.start_time == start_time
        assert result.scheduled_blocks[0].entity_id == task.id
        assert result.scheduled_blocks[0].entity_type == EntityType.TASK
        assert result.scheduled_blocks[0].scheduled_by == ScheduledBy.SYSTEM
        assert result.scheduled_blocks[0].start_time == start_time
        assert result.scheduled_blocks[0].end_time == start_time + timedelta(minutes=30)
    
    def test_schedules_multiple_tasks_sequentially(self, sample_task_base):
        """Test scheduling multiple tasks in sequence."""
        task1 = Task(**{**sample_task_base, "id": str(uuid.uuid4()), "title": "Task 1", "estimated_duration_min": 30})
        task2 = Task(**{**sample_task_base, "id": str(uuid.uuid4()), "title": "Task 2", "estimated_duration_min": 60})
        task3 = Task(**{**sample_task_base, "id": str(uuid.uuid4()), "title": "Task 3", "estimated_duration_min": 30})
        
        start_time = datetime(2024, 1, 1, 10, 0, 0)
        end_time = start_time + timedelta(days=7)
        
        result = schedule_tasks([task1, task2, task3], start_time=start_time, end_time=end_time)
        
        assert len(result.scheduled_blocks) >= 3  # At least 1 block per task
        assert len(result.overflow_tasks) == 0
        assert result.scheduled_blocks[0].entity_id == task1.id
        assert result.scheduled_blocks[0].start_time == start_time
        
        # Find task2 blocks
        task2_blocks = [b for b in result.scheduled_blocks if b.entity_id == task2.id]
        assert len(task2_blocks) >= 1
        # Task2 should start after task1 ends
        assert task2_blocks[0].start_time >= result.scheduled_blocks[0].end_time
    
    def test_skips_manually_scheduled_tasks(self, sample_task_base, manually_scheduled_task):
        """Test that manually scheduled tasks are skipped."""
        normal_task = Task(**{**sample_task_base, "id": str(uuid.uuid4()), "title": "Normal Task"})
        start_time = datetime(2024, 1, 1, 10, 0, 0)
        end_time = start_time + timedelta(days=7)
        
        result = schedule_tasks([manually_scheduled_task, normal_task], start_time=start_time, end_time=end_time)
        
        # Manually scheduled task should not be scheduled
        manual_blocks = [b for b in result.scheduled_blocks if b.entity_id == manually_scheduled_task.id]
        assert len(manual_blocks) == 0
        
        # Normal task should be scheduled
        normal_blocks = [b for b in result.scheduled_blocks if b.entity_id == normal_task.id]
        assert len(normal_blocks) >= 1
    
    def test_handles_overflow_when_insufficient_time(self, sample_task_base):
        """Test that tasks are marked as overflow when insufficient time."""
        task1 = Task(**{**sample_task_base, "id": str(uuid.uuid4()), "estimated_duration_min": 60})
        task2 = Task(**{**sample_task_base, "id": str(uuid.uuid4()), "estimated_duration_min": 60})
        
        start_time = datetime(2024, 1, 1, 10, 0, 0)
        end_time = start_time + timedelta(minutes=90)  # Only 90 minutes available
        
        result = schedule_tasks([task1, task2], start_time=start_time, end_time=end_time)
        
        # First task should be scheduled
        assert len([b for b in result.scheduled_blocks if b.entity_id == task1.id]) >= 1
        # Second task should be in overflow
        assert len(result.overflow_tasks) == 1
        assert result.overflow_tasks[0].id == task2.id
    
    def test_splits_long_task_into_multiple_blocks(self, sample_task_base):
        """Test that long tasks are split into multiple 30-minute blocks."""
        task = Task(**{**sample_task_base, "estimated_duration_min": 90})  # 90 minutes = 3 blocks
        start_time = datetime(2024, 1, 1, 10, 0, 0)
        end_time = start_time + timedelta(days=7)
        
        result = schedule_tasks([task], start_time=start_time, end_time=end_time)
        
        # Should have multiple blocks for the 90-minute task
        task_blocks = [b for b in result.scheduled_blocks if b.entity_id == task.id]
        assert len(task_blocks) >= 3  # At least 3 blocks (30 min each)
        
        # Blocks should be sequential
        for i in range(len(task_blocks) - 1):
            assert task_blocks[i].end_time == task_blocks[i + 1].start_time
    
    def test_deterministic_same_inputs_same_output(self, sample_task_base):
        """Test that same inputs produce same outputs (deterministic)."""
        task1 = Task(**{**sample_task_base, "id": str(uuid.uuid4()), "title": "Task 1", "estimated_duration_min": 30})
        task2 = Task(**{**sample_task_base, "id": str(uuid.uuid4()), "title": "Task 2", "estimated_duration_min": 60})
        tasks = [task1, task2]
        
        start_time = datetime(2024, 1, 1, 10, 0, 0)
        end_time = start_time + timedelta(days=7)
        
        result1 = schedule_tasks(tasks, start_time=start_time, end_time=end_time)
        result2 = schedule_tasks(tasks, start_time=start_time, end_time=end_time)
        result3 = schedule_tasks(tasks, start_time=start_time, end_time=end_time)
        
        # Should have same number of blocks
        assert len(result1.scheduled_blocks) == len(result2.scheduled_blocks) == len(result3.scheduled_blocks)
        assert len(result1.overflow_tasks) == len(result2.overflow_tasks) == len(result3.overflow_tasks)
        
        # Block start/end times should be identical
        for i in range(len(result1.scheduled_blocks)):
            assert result1.scheduled_blocks[i].start_time == result2.scheduled_blocks[i].start_time == result3.scheduled_blocks[i].start_time
            assert result1.scheduled_blocks[i].end_time == result2.scheduled_blocks[i].end_time == result3.scheduled_blocks[i].end_time
    
    def test_rounds_to_granularity(self, sample_task_base):
        """Test that tasks use 30-minute granularity."""
        task = Task(**{**sample_task_base, "estimated_duration_min": 15})  # Less than 30 min
        start_time = datetime(2024, 1, 1, 10, 0, 0)
        end_time = start_time + timedelta(days=7)
        
        result = schedule_tasks([task], start_time=start_time, end_time=end_time)
        
        # Should still use at least one 30-minute block
        assert len(result.scheduled_blocks) >= 1
        block = result.scheduled_blocks[0]
        duration = (block.end_time - block.start_time).total_seconds() / 60
        assert duration >= 15  # At least the task duration
        assert duration <= 30  # But rounded to granularity
    
    def test_stacks_ranked_tasks_in_priority_order(self, sample_task_base):
        """Test that stack-ranked tasks are scheduled in priority order."""
        # Create tasks with different priorities
        high_priority = Task(**{
            **sample_task_base, 
            "id": str(uuid.uuid4()), 
            "title": "High Priority",
            "category": TaskCategory.CHILD,  # Tier 4
            "estimated_duration_min": 30
        })
        low_priority = Task(**{
            **sample_task_base,
            "id": str(uuid.uuid4()),
            "title": "Low Priority",
            "category": TaskCategory.HOME,  # Tier 9
            "estimated_duration_min": 30
        })
        
        # Stack rank tasks (should put high priority first)
        ranked_tasks = stack_rank([low_priority, high_priority])
        
        start_time = datetime(2024, 1, 1, 10, 0, 0)
        end_time = start_time + timedelta(days=7)
        
        result = schedule_tasks(ranked_tasks, start_time=start_time, end_time=end_time)
        
        # High priority task should be scheduled first
        high_blocks = [b for b in result.scheduled_blocks if b.entity_id == high_priority.id]
        low_blocks = [b for b in result.scheduled_blocks if b.entity_id == low_priority.id]
        
        assert len(high_blocks) >= 1
        assert len(low_blocks) >= 1
        assert high_blocks[0].start_time < low_blocks[0].start_time
    
    def test_uses_default_start_time_when_none_provided(self, sample_task):
        """Test that default start_time is used when None."""
        result = schedule_tasks([sample_task])
        
        assert result.start_time is not None
        assert isinstance(result.start_time, datetime)
    
    def test_uses_default_end_time_when_none_provided(self, sample_task):
        """Test that default end_time (7 days) is used when None."""
        start_time = datetime(2024, 1, 1, 10, 0, 0)
        result = schedule_tasks([sample_task], start_time=start_time)
        
        # Should be able to schedule tasks within 7 days
        assert len(result.scheduled_blocks) >= 1
        assert len(result.overflow_tasks) == 0  # Single 30-min task should fit


class TestRoundToGranularity:
    """Test round_to_granularity() function."""
    
    def test_rounds_down_to_nearest_30_minutes(self):
        """Test rounding down to nearest 30-minute boundary."""
        dt = datetime(2024, 1, 1, 10, 45, 30)
        rounded = round_to_granularity(dt)
        
        assert rounded.minute == 30
        assert rounded.second == 0
        assert rounded.microsecond == 0
    
    def test_rounds_down_on_boundary(self):
        """Test rounding on exact boundary."""
        dt = datetime(2024, 1, 1, 10, 30, 0)
        rounded = round_to_granularity(dt)
        
        assert rounded.minute == 30
        assert rounded == dt.replace(second=0, microsecond=0)
    
    def test_rounds_down_below_boundary(self):
        """Test rounding below boundary."""
        dt = datetime(2024, 1, 1, 10, 15, 0)
        rounded = round_to_granularity(dt)
        
        assert rounded.minute == 0
        assert rounded.second == 0
    
    def test_preserves_date_and_hour(self):
        """Test that date and hour are preserved."""
        dt = datetime(2024, 1, 15, 14, 47, 59)
        rounded = round_to_granularity(dt)
        
        assert rounded.year == 2024
        assert rounded.month == 1
        assert rounded.day == 15
        assert rounded.hour == 14
        assert rounded.minute == 30

