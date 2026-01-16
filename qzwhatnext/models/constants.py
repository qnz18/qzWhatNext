"""Constants for qzWhatNext.

This module centralizes all magic numbers and default values used throughout the application.
"""

from qzwhatnext.models.task import EnergyIntensity


# Task defaults
DEFAULT_DURATION_MINUTES = 30
DEFAULT_DURATION_CONFIDENCE = 0.5
DEFAULT_RISK_SCORE = 0.3
DEFAULT_IMPACT_SCORE = 0.3
DEFAULT_ENERGY_INTENSITY = EnergyIntensity.MEDIUM

# Scheduling
SCHEDULING_GRANULARITY_MINUTES = 30

# AI inference confidence thresholds
CATEGORY_CONFIDENCE_THRESHOLD = 0.6
DURATION_CONFIDENCE_THRESHOLD = 0.6

# Duration constraints
MIN_DURATION_MIN = 5  # 5 minutes minimum
MAX_DURATION_MIN = 600  # 600 minutes (10 hours) maximum
DURATION_ROUNDING = 15  # Round to nearest 15 minutes


