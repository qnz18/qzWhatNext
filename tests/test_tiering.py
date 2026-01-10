"""Tests for tier assignment logic (trust-critical, deterministic).

These tests verify that tier assignment is deterministic (same inputs → same outputs)
and follows the fixed priority hierarchy correctly.
"""

import pytest
from datetime import datetime, timedelta
import uuid

from qzwhatnext.engine.tiering import assign_tier, get_tier_name, TIER_DEADLINE_PROXIMITY, TIER_RISK, TIER_IMPACT, TIER_CHILD, TIER_HEALTH, TIER_WORK, TIER_STRESS, TIER_FAMILY, TIER_HOME
from qzwhatnext.models.task import Task, TaskStatus, TaskCategory, EnergyIntensity


class TestTierAssignment:
    """Test assign_tier() function for deterministic behavior."""
    
    def test_tier_1_deadline_proximity(self, sample_task_base):
        """Task with deadline < 24 hours should be Tier 1."""
        deadline = datetime.utcnow() + timedelta(hours=12)
        task = Task(**{**sample_task_base, "deadline": deadline})
        
        tier = assign_tier(task)
        assert tier == TIER_DEADLINE_PROXIMITY
    
    def test_tier_1_deadline_exactly_24_hours(self, sample_task_base):
        """Task with deadline exactly 24 hours away should be Tier 1."""
        deadline = datetime.utcnow() + timedelta(hours=24)
        task = Task(**{**sample_task_base, "deadline": deadline})
        
        tier = assign_tier(task)
        assert tier == TIER_DEADLINE_PROXIMITY
    
    def test_tier_1_not_overdue(self, sample_task_base):
        """Task with deadline in the past should not be Tier 1."""
        deadline = datetime.utcnow() - timedelta(hours=1)
        task = Task(**{**sample_task_base, "deadline": deadline})
        
        tier = assign_tier(task)
        # Should fall through to category-based tier
        assert tier != TIER_DEADLINE_PROXIMITY
    
    def test_tier_2_high_risk_no_deadline(self, task_with_high_risk):
        """Task with high risk score (>=0.7) should be Tier 2 if no urgent deadline."""
        # Ensure no deadline
        task = Task(**{**task_with_high_risk.dict(), "deadline": None})
        
        tier = assign_tier(task)
        assert tier == TIER_RISK
    
    def test_tier_2_high_risk_with_non_urgent_deadline(self, sample_task_base):
        """Task with high risk and deadline > 24h should be Tier 2."""
        deadline = datetime.utcnow() + timedelta(days=2)
        task = Task(**{**sample_task_base, "risk_score": 0.8, "deadline": deadline})
        
        tier = assign_tier(task)
        assert tier == TIER_RISK
    
    def test_tier_2_not_high_risk(self, sample_task_base):
        """Task with risk_score < 0.7 should not be Tier 2."""
        task = Task(**{**sample_task_base, "risk_score": 0.6})
        
        tier = assign_tier(task)
        assert tier != TIER_RISK
    
    def test_tier_3_high_impact_no_higher_tiers(self, task_with_high_impact):
        """Task with high impact score (>=0.7) should be Tier 3 if no higher tier applies."""
        # Ensure no deadline, no high risk
        task = Task(**{**task_with_high_impact.dict(), "deadline": None, "risk_score": 0.6})
        
        tier = assign_tier(task)
        assert tier == TIER_IMPACT
    
    def test_tier_3_not_high_impact(self, sample_task_base):
        """Task with impact_score < 0.7 should not be Tier 3."""
        task = Task(**{**sample_task_base, "impact_score": 0.6})
        
        tier = assign_tier(task)
        assert tier != TIER_IMPACT
    
    def test_tier_4_child_category(self, child_task):
        """Task with CHILD category should be Tier 4."""
        tier = assign_tier(child_task)
        assert tier == TIER_CHILD
    
    def test_tier_5_health_category(self, health_task):
        """Task with HEALTH category should be Tier 5."""
        tier = assign_tier(health_task)
        assert tier == TIER_HEALTH
    
    def test_tier_6_work_category(self, work_task):
        """Task with WORK category should be Tier 6."""
        tier = assign_tier(work_task)
        assert tier == TIER_WORK
    
    def test_tier_7_personal_category(self, sample_task_base):
        """Task with PERSONAL category should be Tier 7."""
        task = Task(**{**sample_task_base, "category": TaskCategory.PERSONAL})
        
        tier = assign_tier(task)
        assert tier == TIER_STRESS
    
    def test_tier_7_ideas_category(self, sample_task_base):
        """Task with IDEAS category should be Tier 7."""
        task = Task(**{**sample_task_base, "category": TaskCategory.IDEAS})
        
        tier = assign_tier(task)
        assert tier == TIER_STRESS
    
    def test_tier_8_family_category(self, family_task):
        """Task with FAMILY category should be Tier 8."""
        tier = assign_tier(family_task)
        assert tier == TIER_FAMILY
    
    def test_tier_9_home_category(self, home_task):
        """Task with HOME category should be Tier 9."""
        tier = assign_tier(home_task)
        assert tier == TIER_HOME
    
    def test_tier_9_admin_category(self, sample_task_base):
        """Task with ADMIN category should be Tier 9."""
        task = Task(**{**sample_task_base, "category": TaskCategory.ADMIN})
        
        tier = assign_tier(task)
        assert tier == TIER_HOME
    
    def test_tier_9_unknown_category(self, sample_task):
        """Task with UNKNOWN category should be Tier 9 (default)."""
        tier = assign_tier(sample_task)
        assert tier == TIER_HOME
    
    def test_tier_hierarchy_deadline_overrides_category(self, child_task):
        """Deadline tier should override category tier."""
        deadline = datetime.utcnow() + timedelta(hours=12)
        task = Task(**{**child_task.dict(), "deadline": deadline})
        
        tier = assign_tier(task)
        assert tier == TIER_DEADLINE_PROXIMITY  # Not TIER_CHILD
    
    def test_tier_hierarchy_risk_overrides_category(self, child_task):
        """Risk tier should override category tier if no deadline."""
        task = Task(**{**child_task.dict(), "risk_score": 0.8, "deadline": None})
        
        tier = assign_tier(task)
        assert tier == TIER_RISK  # Not TIER_CHILD
    
    def test_tier_hierarchy_impact_overrides_category(self, child_task):
        """Impact tier should override category tier if no deadline or risk."""
        task = Task(**{**child_task.dict(), "impact_score": 0.8, "deadline": None, "risk_score": 0.6})
        
        tier = assign_tier(task)
        assert tier == TIER_IMPACT  # Not TIER_CHILD
    
    def test_deterministic_same_inputs_same_output(self, sample_task):
        """Same task should always get same tier (deterministic)."""
        tier1 = assign_tier(sample_task)
        tier2 = assign_tier(sample_task)
        tier3 = assign_tier(sample_task)
        
        assert tier1 == tier2 == tier3
    
    def test_deterministic_multiple_runs(self, sample_task_base):
        """Multiple tasks with same attributes should get same tier."""
        task1 = Task(**{**sample_task_base, "id": str(uuid.uuid4()), "category": TaskCategory.WORK})
        task2 = Task(**{**sample_task_base, "id": str(uuid.uuid4()), "category": TaskCategory.WORK})
        task3 = Task(**{**sample_task_base, "id": str(uuid.uuid4()), "category": TaskCategory.WORK})
        
        tier1 = assign_tier(task1)
        tier2 = assign_tier(task2)
        tier3 = assign_tier(task3)
        
        assert tier1 == tier2 == tier3 == TIER_WORK


class TestGetTierName:
    """Test get_tier_name() function."""
    
    def test_all_tier_names(self):
        """Test all tier names are correct."""
        assert get_tier_name(1) == "Deadline Proximity"
        assert get_tier_name(2) == "Risk of Negative Consequence"
        assert get_tier_name(3) == "Downstream Impact"
        assert get_tier_name(4) == "Child-Related Needs"
        assert get_tier_name(5) == "Personal Health Needs"
        assert get_tier_name(6) == "Work Obligations"
        assert get_tier_name(7) == "Stress Reduction"
        assert get_tier_name(8) == "Family/Social Commitments"
        assert get_tier_name(9) == "Home Care"
    
    def test_invalid_tier_name(self):
        """Invalid tier should return 'Unknown'."""
        assert get_tier_name(0) == "Unknown"
        assert get_tier_name(10) == "Unknown"
        assert get_tier_name(-1) == "Unknown"

