"""AI inference logic for task attributes.

This module handles AI-assisted inference of task attributes including
category, duration, energy intensity, risk score, and impact score.

NOTE: This is a placeholder for future AI inference implementation.
When implemented, it should:
1. Check AI exclusion BEFORE any inference calls
2. Use 'unknown' category when confidence is low (< threshold, e.g., 0.6)
3. Provide confidence scores for all inferred attributes
4. Never assign priority tiers (tiering is deterministic)
"""

from typing import Optional, Tuple
from qzwhatnext.models.task import Task, TaskCategory
from qzwhatnext.engine.ai_exclusion import is_ai_excluded

# Confidence threshold for using 'unknown' category
CATEGORY_CONFIDENCE_THRESHOLD = 0.6


def infer_category(task: Task) -> Tuple[TaskCategory, float]:
    """Infer task category with confidence score.
    
    NOTE: This is a placeholder. When AI inference is implemented:
    - Check AI exclusion BEFORE calling
    - Use 'unknown' category when confidence < CATEGORY_CONFIDENCE_THRESHOLD
    - Return (category, confidence) where confidence is 0.0-1.0
    
    Args:
        task: Task to infer category for
        
    Returns:
        Tuple of (category, confidence_score)
    """
    # Placeholder: always return UNKNOWN with low confidence
    # This signals that AI inference is not yet implemented
    return (TaskCategory.UNKNOWN, 0.0)


def infer_task_attributes(task: Task) -> Optional[Task]:
    """Infer task attributes using AI (if not excluded).
    
    This function should:
    1. Check AI exclusion BEFORE any AI calls
    2. Infer category with confidence
    3. Use 'unknown' category if confidence < threshold
    4. Infer other attributes (duration, energy, risk, impact)
    5. Return updated task (or None if task is AI-excluded)
    
    Args:
        task: Task to infer attributes for
        
    Returns:
        Updated task with inferred attributes, or None if AI-excluded
    """
    # Check AI exclusion BEFORE any inference
    if is_ai_excluded(task):
        return None
    
    # Placeholder: AI inference not yet implemented
    # When implemented, should infer:
    # - category (use 'unknown' if confidence < threshold)
    # - estimated_duration_min
    # - duration_confidence
    # - energy_intensity
    # - risk_score
    # - impact_score
    # - dependencies
    
    return task

