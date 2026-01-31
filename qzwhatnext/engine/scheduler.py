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

        # If task has a flexibility window, it must be scheduled entirely within it.
        window_start: Optional[datetime] = None
        window_end: Optional[datetime] = None
        if task.flexibility_window:
            try:
                window_start, window_end = task.flexibility_window
            except Exception:
                window_start, window_end = None, None
            if window_start is not None and window_end is not None and window_end <= window_start:
                # Invalid window: treat as unschedulable in MVP (overflow).
                result.overflow_tasks.append(task)
                continue
        
        # Calculate how many 30-minute blocks we need
        duration_minutes = task.estimated_duration_min
        blocks_needed = max(1, (duration_minutes + SCHEDULING_GRANULARITY_MINUTES - 1) // SCHEDULING_GRANULARITY_MINUTES)
        total_duration = blocks_needed * SCHEDULING_GRANULARITY_MINUTES

        # Establish earliest candidate start for this task (respecting flexibility window).
        task_start = current_time
        if window_start is not None:
            task_start = max(task_start, window_start)
        if window_end is not None and task_start >= window_end:
            result.overflow_tasks.append(task)
            continue

        # Fast coarse check (does not account for reserved jumps, but avoids work when impossible).
        if task_start + timedelta(minutes=total_duration) > end_time:
            result.overflow_tasks.append(task)
            continue
        if window_end is not None and task_start + timedelta(minutes=total_duration) > window_end:
            result.overflow_tasks.append(task)
            continue

        # Create scheduled blocks for this task (all-or-nothing within window).
        remaining_duration = duration_minutes
        candidate_start = task_start
        new_blocks: List[ScheduledBlock] = []
        failed = False

        while remaining_duration > 0:
            block_duration = min(remaining_duration, SCHEDULING_GRANULARITY_MINUTES)
            candidate_start = next_available_time(candidate_start, block_duration)
            block_end = candidate_start + timedelta(minutes=block_duration)

            if block_end > end_time:
                failed = True
                break
            if window_end is not None and block_end > window_end:
                failed = True
                break

            new_blocks.append(
                ScheduledBlock(
                    id=str(uuid.uuid4()),
                    user_id=task.user_id,
                    entity_type=EntityType.TASK,
                    entity_id=task.id,
                    start_time=candidate_start,
                    end_time=block_end,
                    scheduled_by=ScheduledBy.SYSTEM,
                    locked=False,
                )
            )

            candidate_start = block_end
            remaining_duration -= block_duration

        if failed:
            result.overflow_tasks.append(task)
            continue

        result.scheduled_blocks.extend(new_blocks)
        current_time = candidate_start
    
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

