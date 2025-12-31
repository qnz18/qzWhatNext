"""Scheduling algorithm for qzWhatNext.

Places tasks into calendar time blocks based on stack ranking.
For minimal MVP, assumes all time is free (no calendar conflict checking).
"""

import uuid
from datetime import datetime, timedelta
from typing import List, Optional
from qzwhatnext.models.task import Task
from qzwhatnext.models.scheduled_block import ScheduledBlock, EntityType, ScheduledBy


# Default scheduling granularity: 30 minutes
SCHEDULING_GRANULARITY_MINUTES = 30


class SchedulingResult:
    """Result of scheduling operation."""
    
    def __init__(self):
        self.scheduled_blocks: List[ScheduledBlock] = []
        self.overflow_tasks: List[Task] = []
        self.start_time: Optional[datetime] = None


def schedule_tasks(
    tasks: List[Task],
    start_time: Optional[datetime] = None,
    end_time: Optional[datetime] = None,
) -> SchedulingResult:
    """Schedule tasks into time blocks.
    
    For minimal MVP:
    - Assumes all time is free (no calendar conflict checking)
    - Places tasks in order starting from start_time
    - Uses 30-minute minimum blocks
    - Splits tasks across multiple blocks if needed
    
    Args:
        tasks: List of tasks in stack-ranked order
        start_time: When to start scheduling (defaults to now)
        end_time: When to stop scheduling (defaults to 7 days from start)
        
    Returns:
        SchedulingResult with scheduled blocks and overflow tasks
    """
    result = SchedulingResult()
    
    # Set default start time (now) and end time (7 days from start)
    if start_time is None:
        start_time = datetime.utcnow()
    if end_time is None:
        end_time = start_time + timedelta(days=7)
    
    result.start_time = start_time
    
    current_time = start_time
    
    for task in tasks:
        # Skip if manually scheduled (system doesn't move these)
        if task.manually_scheduled:
            continue
        
        # Calculate how many 30-minute blocks we need
        duration_minutes = task.estimated_duration_min
        blocks_needed = max(1, (duration_minutes + SCHEDULING_GRANULARITY_MINUTES - 1) // SCHEDULING_GRANULARITY_MINUTES)
        total_duration = blocks_needed * SCHEDULING_GRANULARITY_MINUTES
        
        # Check if we have enough time before end_time
        if current_time + timedelta(minutes=total_duration) > end_time:
            result.overflow_tasks.append(task)
            continue
        
        # Create scheduled blocks for this task
        remaining_duration = duration_minutes
        task_start = current_time
        
        while remaining_duration > 0:
            block_duration = min(remaining_duration, SCHEDULING_GRANULARITY_MINUTES)
            block_end = task_start + timedelta(minutes=block_duration)
            
            block = ScheduledBlock(
                id=str(uuid.uuid4()),
                entity_type=EntityType.TASK,
                entity_id=task.id,
                start_time=task_start,
                end_time=block_end,
                scheduled_by=ScheduledBy.SYSTEM,
                locked=False,
            )
            
            result.scheduled_blocks.append(block)
            
            # Move to next block
            task_start = block_end
            remaining_duration -= block_duration
        
        # Move current time forward
        current_time = task_start
    
    return result


def round_to_granularity(dt: datetime) -> datetime:
    """Round datetime to scheduling granularity (30 minutes).
    
    Args:
        dt: Datetime to round
        
    Returns:
        Rounded datetime
    """
    # Round down to nearest 30-minute boundary
    minutes = dt.minute
    rounded_minutes = (minutes // SCHEDULING_GRANULARITY_MINUTES) * SCHEDULING_GRANULARITY_MINUTES
    
    return dt.replace(minute=rounded_minutes, second=0, microsecond=0)

