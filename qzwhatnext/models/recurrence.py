"""Recurrence models (simple presets) for qzWhatNext.

Canonical internal representation for repeating tasks/time blocks.
Users never need to enter RRULE strings; RRULE is export-only for Google Calendar.
"""

from __future__ import annotations

from datetime import date, time
from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field, field_validator


class RecurrenceFrequency(str, Enum):
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    YEARLY = "yearly"


class TimeOfDayWindow(str, Enum):
    """Named time windows (local to user's calendar timezone)."""

    WAKE_UP = "wake_up"
    MORNING = "morning"
    AFTERNOON = "afternoon"
    EVENING = "evening"
    NIGHT = "night"


class Weekday(str, Enum):
    MO = "mo"
    TU = "tu"
    WE = "we"
    TH = "th"
    FR = "fr"
    SA = "sa"
    SU = "su"


class RecurrencePreset(BaseModel):
    """Simple recurrence definition.

    Notes:
    - Times are interpreted in the user's Google Calendar timezone for time blocks.
    - For recurring task series, time-of-day windows can be translated into a Task flexibility window.
    """

    frequency: RecurrenceFrequency
    interval: int = Field(1, ge=1, description="Every N units (days/weeks/months/years)")

    # Weekly specifics
    by_weekday: Optional[List[Weekday]] = Field(
        None, description="For weekly recurrence: weekdays on which it occurs"
    )
    count_per_period: Optional[int] = Field(
        None, ge=1, description="For patterns like '3 times per week'"
    )

    # Time block specifics (may span midnight if end < start)
    time_start: Optional[time] = None
    time_end: Optional[time] = None

    # Task-series windowing
    time_of_day_window: Optional[TimeOfDayWindow] = None

    # Range
    start_date: Optional[date] = None
    until_date: Optional[date] = None

    @field_validator("by_weekday")
    @classmethod
    def _validate_by_weekday(cls, v, info):
        if v is None:
            return None
        # Deduplicate but preserve order
        seen = set()
        out: List[Weekday] = []
        for day in v:
            if day not in seen:
                seen.add(day)
                out.append(day)
        return out

    @field_validator("until_date")
    @classmethod
    def _validate_until_date(cls, v, info):
        start = info.data.get("start_date")
        if v is not None and start is not None and v < start:
            raise ValueError("until_date must be >= start_date")
        return v

