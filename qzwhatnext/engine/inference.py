"""AI inference logic for task attributes.

This module handles AI-assisted inference of task attributes including
category, duration, energy intensity, risk score, impact score, and title generation.

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
from qzwhatnext.models.constants import (
    CATEGORY_CONFIDENCE_THRESHOLD,
    DURATION_CONFIDENCE_THRESHOLD,
    MIN_DURATION_MIN,
    MAX_DURATION_MIN,
    DURATION_ROUNDING,
)

logger = logging.getLogger(__name__)

# Re-export constants for backward compatibility
__all__ = [
    'CATEGORY_CONFIDENCE_THRESHOLD',
    'DURATION_CONFIDENCE_THRESHOLD',
    'MIN_DURATION_MIN',
    'MAX_DURATION_MIN',
    'DURATION_ROUNDING',
]

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


def generate_title(task: Task, max_length: int = 100) -> Optional[str]:
    """Generate a concise title from task notes using OpenAI API.
    
    This function:
    - Checks AI exclusion BEFORE calling OpenAI (trust-critical)
    - Returns None if task is AI-excluded or generation fails
    - Returns generated title string if successful
    
    Args:
        task: Task to generate title for
        max_length: Maximum length of the generated title (default: 100)
        
    Returns:
        Generated title string, or None if:
        - Task is AI-excluded
        - Notes are empty
        - Generation fails
    """
    # Check AI exclusion BEFORE any inference calls (trust-critical)
    if is_ai_excluded(task):
        logger.debug(f"Task {task.id} is AI-excluded. Skipping title generation.")
        return None
    
    # Extract notes for inference
    notes = task.notes or ""
    
    # If no notes, return None
    if not notes.strip():
        logger.debug(f"Task {task.id} has no notes. Skipping title generation.")
        return None
    
    # Call OpenAI client to generate title
    try:
        openai_client = _get_openai_client()
        title = openai_client.generate_title(notes, max_length=max_length)
        
        if title and title.strip():
            logger.debug(f"Task {task.id} generated title: {title[:50]}...")
            return title.strip()
        else:
            logger.debug(f"Task {task.id} title generation returned empty string")
            return None
        
    except Exception as e:
        # Handle any errors gracefully - don't fail task creation
        logger.error(f"Error generating title for task {task.id}: {type(e).__name__}")
        return None


def estimate_duration(task: Task) -> Tuple[int, float]:
    """Estimate task duration with confidence score.
    
    This function:
    - Checks AI exclusion BEFORE calling OpenAI (trust-critical)
    - Applies constraints: rounding to 15 min, bounds (5-600 min)
    - Uses default duration if confidence < threshold
    - Returns (duration_minutes, confidence) where duration is 0 if estimation failed
    
    Args:
        task: Task to estimate duration for
        
    Returns:
        Tuple of (duration_minutes, confidence_score) where:
        - duration_minutes is an integer in minutes (0 if estimation failed or below threshold)
        - confidence is 0.0-1.0
    """
    # Check AI exclusion BEFORE any inference calls (trust-critical)
    if is_ai_excluded(task):
        logger.debug(f"Task {task.id} is AI-excluded. Returning duration 0.")
        return (0, 0.0)
    
    # Extract notes for inference
    notes = task.notes or ""
    
    # If no notes, return 0 duration
    if not notes.strip():
        logger.debug(f"Task {task.id} has no notes. Returning duration 0.")
        return (0, 0.0)
    
    # Call OpenAI client to estimate duration
    try:
        openai_client = _get_openai_client()
        duration_min, confidence = openai_client.estimate_duration(notes)
        
        # If estimation failed, return 0
        if duration_min == 0:
            logger.debug(f"Task {task.id} duration estimation returned 0 (failed)")
            return (0, 0.0)
        
        # Apply confidence threshold: return 0 if confidence is too low
        if confidence < DURATION_CONFIDENCE_THRESHOLD:
            logger.debug(f"Task {task.id} duration inference confidence {confidence} below threshold {DURATION_CONFIDENCE_THRESHOLD}. Returning 0.")
            return (0, 0.0)
        
        # Apply constraints: round to nearest 15 minutes
        rounded_duration = round(duration_min / DURATION_ROUNDING) * DURATION_ROUNDING
        
        # Enforce minimum (5 minutes)
        if rounded_duration < MIN_DURATION_MIN:
            logger.debug(f"Task {task.id} duration {rounded_duration} below minimum {MIN_DURATION_MIN}. Using minimum.")
            rounded_duration = MIN_DURATION_MIN
        
        # Enforce maximum (600 minutes / 10 hours)
        if rounded_duration > MAX_DURATION_MIN:
            logger.debug(f"Task {task.id} duration {rounded_duration} above maximum {MAX_DURATION_MIN}. Using maximum.")
            rounded_duration = MAX_DURATION_MIN
        
        logger.debug(f"Task {task.id} estimated duration: {rounded_duration} minutes (original: {duration_min}) with confidence {confidence}")
        return (rounded_duration, confidence)
        
    except Exception as e:
        # Handle any errors gracefully - don't fail task creation
        logger.error(f"Error estimating duration for task {task.id}: {type(e).__name__}")
        return (0, 0.0)


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

