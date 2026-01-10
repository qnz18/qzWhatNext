"""AI inference logic for task attributes.

This module handles AI-assisted inference of task attributes including
category, duration, energy intensity, risk score, and impact score.

1. Check AI exclusion BEFORE any inference calls
2. Use 'unknown' category when confidence is low (< threshold, e.g., 0.6)
3. Provide confidence scores for all inferred attributes
4. Never assign priority tiers (tiering is deterministic)
"""

import logging
from typing import Optional, Tuple
from qzwhatnext.models.task import Task, TaskCategory
from qzwhatnext.engine.ai_exclusion import is_ai_excluded
from qzwhatnext.integrations.openai_client import OpenAIClient

logger = logging.getLogger(__name__)

# Confidence threshold for using 'unknown' category
CATEGORY_CONFIDENCE_THRESHOLD = 0.6

# Initialize OpenAI client (singleton pattern)
_openai_client: Optional[OpenAIClient] = None


def _get_openai_client() -> OpenAIClient:
    """Get or create OpenAI client instance."""
    global _openai_client
    if _openai_client is None:
        _openai_client = OpenAIClient()
    return _openai_client


def infer_category(task: Task) -> Tuple[TaskCategory, float]:
    """Infer task category with confidence score.
    
    This function:
    - Checks AI exclusion BEFORE calling OpenAI
    - Uses 'unknown' category when confidence < CATEGORY_CONFIDENCE_THRESHOLD
    - Returns (category, confidence) where confidence is 0.0-1.0
    
    Args:
        task: Task to infer category for
        
    Returns:
        Tuple of (category, confidence_score)
    """
    # Check AI exclusion BEFORE any inference calls (trust-critical)
    if is_ai_excluded(task):
        logger.debug(f"Task {task.id} is AI-excluded. Returning UNKNOWN category.")
        return (TaskCategory.UNKNOWN, 0.0)
    
    # Extract notes for inference
    notes = task.notes or ""
    
    # If no notes, return UNKNOWN
    if not notes.strip():
        logger.debug(f"Task {task.id} has no notes. Returning UNKNOWN category.")
        return (TaskCategory.UNKNOWN, 0.0)
    
    # Call OpenAI client to infer category
    try:
        openai_client = _get_openai_client()
        category, confidence = openai_client.infer_category(notes)
        
        # Apply confidence threshold: use UNKNOWN if confidence is too low
        if confidence < CATEGORY_CONFIDENCE_THRESHOLD:
            logger.debug(f"Task {task.id} category inference confidence {confidence} below threshold {CATEGORY_CONFIDENCE_THRESHOLD}. Using UNKNOWN.")
            return (TaskCategory.UNKNOWN, 0.0)
        
        logger.debug(f"Task {task.id} inferred category: {category.value} with confidence {confidence}")
        return (category, confidence)
        
    except Exception as e:
        # Handle any errors gracefully - don't fail task creation
        logger.error(f"Error inferring category for task {task.id}: {type(e).__name__}")
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

