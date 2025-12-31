"""Tier assignment logic for qzWhatNext.

Implements the fixed priority hierarchy for deterministic tier assignment.
Each task has exactly one governing priority tier at any moment.
"""

from datetime import datetime, timedelta
from typing import Optional
from qzwhatnext.models.task import Task, TaskCategory


# Fixed priority tier hierarchy (highest to lowest)
# Each tier number corresponds to the hierarchy position
TIER_DEADLINE_PROXIMITY = 1
TIER_RISK = 2
TIER_IMPACT = 3
TIER_CHILD = 4
TIER_HEALTH = 5
TIER_WORK = 6
TIER_STRESS = 7
TIER_FAMILY = 8
TIER_HOME = 9


def assign_tier(task: Task) -> int:
    """Assign a priority tier to a task based on the fixed hierarchy.
    
    The task is assigned to the HIGHEST applicable tier.
    This function is deterministic - same inputs always produce same outputs.
    
    Args:
        task: The task to assign a tier to
        
    Returns:
        Tier number (1-9, where 1 is highest priority)
    """
    # Check tiers in order of priority (highest first)
    
    # Tier 1: Deadline proximity
    if _has_urgent_deadline(task):
        return TIER_DEADLINE_PROXIMITY
    
    # Tier 2: Risk of negative consequence
    if _has_high_risk(task):
        return TIER_RISK
    
    # Tier 3: Downstream impact
    if _has_high_impact(task):
        return TIER_IMPACT
    
    # Tier 4: Child-related needs
    if task.category == TaskCategory.CHILD:
        return TIER_CHILD
    
    # Tier 5: Personal health needs
    if task.category == TaskCategory.HEALTH:
        return TIER_HEALTH
    
    # Tier 6: Work obligations
    if task.category == TaskCategory.WORK:
        return TIER_WORK
    
    # Tier 7: Stress reduction
    if task.category == TaskCategory.STRESS:
        return TIER_STRESS
    
    # Tier 8: Family/social commitments
    if task.category in [TaskCategory.FAMILY, TaskCategory.SOCIAL]:
        return TIER_FAMILY
    
    # Tier 9: Home care (default)
    if task.category == TaskCategory.HOME:
        return TIER_HOME
    
    # Default to lowest tier for uncategorized tasks
    return TIER_HOME


def _has_urgent_deadline(task: Task) -> bool:
    """Check if task has an urgent deadline (< 24 hours).
    
    Args:
        task: Task to check
        
    Returns:
        True if deadline is within 24 hours
    """
    if not task.deadline:
        return False
    
    now = datetime.utcnow()
    if task.deadline.tzinfo:
        # Convert to UTC if timezone-aware
        now = datetime.now(task.deadline.tzinfo)
    
    time_until_deadline = task.deadline - now
    return time_until_deadline <= timedelta(hours=24) and time_until_deadline.total_seconds() > 0


def _has_high_risk(task: Task) -> bool:
    """Check if task has high risk score.
    
    Args:
        task: Task to check
        
    Returns:
        True if risk_score >= 0.7
    """
    return task.risk_score >= 0.7


def _has_high_impact(task: Task) -> bool:
    """Check if task has high impact score.
    
    Args:
        task: Task to check
        
    Returns:
        True if impact_score >= 0.7
    """
    return task.impact_score >= 0.7


def get_tier_name(tier: int) -> str:
    """Get human-readable name for a tier.
    
    Args:
        tier: Tier number (1-9)
        
    Returns:
        Tier name string
    """
    tier_names = {
        1: "Deadline Proximity",
        2: "Risk of Negative Consequence",
        3: "Downstream Impact",
        4: "Child-Related Needs",
        5: "Personal Health Needs",
        6: "Work Obligations",
        7: "Stress Reduction",
        8: "Family/Social Commitments",
        9: "Home Care",
    }
    return tier_names.get(tier, "Unknown")

