"""Scheduling algorithm for qzWhatNext.

Places tasks into calendar time blocks based on stack ranking.
For minimal MVP, assumes all time is free (no calendar conflict checking).
"""

import uuid
from datetime import datetime, timedelta
from typing import List, Optional, Tuple
from qzwhatnext.models.task import Task
from qzwhatnext.models.scheduled_block import ScheduledBlock, EntityType, ScheduledBy
from qzwhatnext.models.constants import SCHEDULING_GRANULARITY_MINUTES

# Re-export for backward compatibility
__all__ = ['SCHEDULING_GRANULARITY_MINUTES']


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
    reserved_intervals: Optional[List[Tuple[datetime, datetime]]] = None,
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
        reserved_intervals: Optional list of fixed [start, end) intervals that may not be overlapped.
        
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

    # Normalize reserved intervals: sort and drop invalid/empty.
    reserved: List[Tuple[datetime, datetime]] = []
    for s, e in (reserved_intervals or []):
        if s is None or e is None:
            continue
        if e <= s:
            continue
        reserved.append((s, e))
    reserved.sort(key=lambda x: x[0])

    def next_available_time(t: datetime, duration_min: int) -> datetime:
        """Return the earliest start time at/after t that fits without overlapping reserved intervals."""
        if not reserved:
            return t
        while True:
            moved = False
            block_end = t + timedelta(minutes=duration_min)
            for rs, re in reserved:
                # Already past this reserved block.
                if re <= t:
                    continue
                # If we're inside a reserved block, jump to its end.
                if rs <= t < re:
                    t = re
                    moved = True
                    break
                # If this candidate block would overlap the next reserved block, but we don't have enough room, skip it.
                if t < rs and block_end > rs:
                    # Not enough gap to place this block: jump to end of reserved interval.
                    t = re
                    moved = True
                    break
            if not moved:
                return t
    
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
            task_start = next_available_time(task_start, block_duration)
            block_end = task_start + timedelta(minutes=block_duration)
            
            block = ScheduledBlock(
                id=str(uuid.uuid4()),
                user_id=task.user_id,
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

