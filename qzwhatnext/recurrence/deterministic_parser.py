"""Deterministic parser for recurring capture instructions.

This module converts casual user text into a structured RecurrencePreset + entity kind.
It must be deterministic: same input -> same output (or same structured error).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time
import re
from datetime import timedelta
from typing import List, Optional, Tuple

from qzwhatnext.models.recurrence import (
    RecurrenceFrequency,
    RecurrencePreset,
    TimeOfDayWindow,
    Weekday,
)


class RecurrenceParseError(ValueError):
    """Structured parse error that can be surfaced as a 400."""

    def __init__(self, message: str, *, missing: Optional[list[str]] = None):
        super().__init__(message)
        self.missing = missing or []


@dataclass(frozen=True)
class ParsedCapture:
    entity_kind: str  # "task_series" | "time_block"
    title: str
    preset: RecurrencePreset
    ai_excluded: bool


_WEEKDAY_ALIASES: list[tuple[re.Pattern, Weekday]] = [
    (re.compile(r"\b(mon|monday)\b", re.I), Weekday.MO),
    (re.compile(r"\b(tue|tues|tuesday)\b", re.I), Weekday.TU),
    (re.compile(r"\b(wed|weds|wednesday)\b", re.I), Weekday.WE),
    (re.compile(r"\b(thu|thur|thurs|thursday)\b", re.I), Weekday.TH),
    (re.compile(r"\b(fri|friday)\b", re.I), Weekday.FR),
    (re.compile(r"\b(sat|saturday)\b", re.I), Weekday.SA),
    (re.compile(r"\b(sun|sunday)\b", re.I), Weekday.SU),
]


def _extract_weekdays(text: str) -> List[Weekday]:
    """Extract all mentioned weekdays (deduped, stable order)."""
    out: List[Weekday] = []
    for pat, day in _WEEKDAY_ALIASES:
        if pat.search(text):
            out.append(day)
    # Deduplicate while preserving order
    seen = set()
    unique: List[Weekday] = []
    for d in out:
        if d not in seen:
            seen.add(d)
            unique.append(d)
    return unique


_TIME_RE = re.compile(
    r"\b(?P<h>\d{1,2})(?::(?P<m>\d{2}))?\s*(?P<ampm>am|pm)?\b", re.I
)


def _parse_time_token(token: str, *, context: str) -> time:
    m = _TIME_RE.search(token.strip())
    if not m:
        raise RecurrenceParseError("Could not parse time")
    h = int(m.group("h"))
    minute = int(m.group("m") or "0")
    ampm = (m.group("ampm") or "").lower()
    if h < 0 or h > 23 or minute < 0 or minute > 59:
        raise RecurrenceParseError("Invalid time")

    # If AM/PM provided, normalize to 24h.
    if ampm:
        if h == 12:
            h = 0
        if ampm == "pm":
            h += 12
    else:
        # Deterministic heuristic for ambiguous times:
        # - In a weekday+time context (kids practice Tue 4:30), interpret 1..7 as PM.
        # - Otherwise keep as-is (e.g. "7" means 07:00).
        if context == "weekday_time" and 1 <= h <= 7:
            h += 12

    if h > 23:
        raise RecurrenceParseError("Invalid time")
    return time(hour=h, minute=minute)


def _extract_time_range(text: str) -> Optional[Tuple[time, time]]:
    # Match "11pm to 7am", "11pm-7am", "11pm – 7am"
    m = re.search(r"(.+?)\s*(?:to|\-|\u2013|\u2014)\s*(.+)", text, re.I)
    if not m:
        return None
    left = m.group(1)
    right = m.group(2)
    try:
        t1 = _parse_time_token(left, context="range")
        t2 = _parse_time_token(right, context="range")
        return (t1, t2)
    except RecurrenceParseError:
        return None


def _extract_duration_minutes(text: str) -> Optional[int]:
    """Extract explicit duration like 'for 90 min' or 'for 1.5 hours'."""
    t = (text or "").lower()
    m = re.search(r"\bfor\s+(\d+(?:\.\d+)?)\s*(min|mins|minute|minutes)\b", t)
    if m:
        minutes = float(m.group(1))
        return max(int(round(minutes)), 1)
    h = re.search(r"\bfor\s+(\d+(?:\.\d+)?)\s*(hr|hrs|hour|hours)\b", t)
    if h:
        hours = float(h.group(1))
        return max(int(round(hours * 60)), 1)
    return None


def _detect_time_of_day_window(text: str) -> Optional[TimeOfDayWindow]:
    t = text.lower()
    if "wake up" in t or "wakeup" in t or "wake-up" in t:
        return TimeOfDayWindow.WAKE_UP
    if "morning" in t:
        return TimeOfDayWindow.MORNING
    if "afternoon" in t:
        return TimeOfDayWindow.AFTERNOON
    if "evening" in t:
        return TimeOfDayWindow.EVENING
    if "night" in t:
        return TimeOfDayWindow.NIGHT
    return None


def parse_capture_instruction(text: str, *, now: Optional[datetime] = None) -> ParsedCapture:
    """Parse a user instruction into a structured capture object.

    Supported patterns (MVP):
    - "bed time every day from 11pm to 7am" -> daily time block
    - "kids practice tues at 4:30" -> weekly time block
    - "take my vitamins every morning" -> daily task series with time-of-day window
    - "go to the gym 3 times per week" -> weekly task series with count_per_period
    - "replace air filters every 3 months" -> monthly task series (interval=3)
    - "flush water heater once per year in the fall" -> yearly task series
    """
    now = now or datetime.utcnow()
    raw = (text or "").strip()
    if not raw:
        raise RecurrenceParseError("Instruction is required", missing=["instruction"])

    ai_excluded = raw.startswith(".")
    normalized = raw.lstrip(".").strip()

    # Very simple title extraction: use the normalized instruction as title for now.
    # (We can refine later with AI title generation when allowed.)
    title = normalized

    # Determine if this should be a time block.
    weekdays = _extract_weekdays(normalized)
    time_range = _extract_time_range(normalized)
    duration_min = _extract_duration_minutes(normalized)

    # Detect patterns like "tues at 4:30"
    weekday_time: Optional[time] = None
    if weekdays:
        # Prefer explicit "at 4:30pm" form.
        m = re.search(r"\bat\s+(.+)$", normalized, re.I)
        if m:
            try:
                weekday_time = _parse_time_token(m.group(1), context="weekday_time")
            except RecurrenceParseError:
                weekday_time = None

        # If user omits "at" (e.g., "tues and thurs 2:30pm"), fall back to the last time-like token.
        if weekday_time is None and not time_range:
            matches = list(_TIME_RE.finditer(normalized))
            if matches:
                try:
                    weekday_time = _parse_time_token(matches[-1].group(0), context="weekday_time")
                except RecurrenceParseError:
                    weekday_time = None

    is_time_block = bool(time_range) or (bool(weekdays) and weekday_time is not None)
    entity_kind = "time_block" if is_time_block else "task_series"

    # Frequency / interval
    freq = None
    interval = 1
    m_every_n = re.search(r"\bevery\s+(\d+)\s+(day|days|week|weeks|month|months|year|years)\b", normalized, re.I)
    if m_every_n:
        interval = int(m_every_n.group(1))
        unit = m_every_n.group(2).lower()
        if "day" in unit:
            freq = RecurrenceFrequency.DAILY
        elif "week" in unit:
            freq = RecurrenceFrequency.WEEKLY
        elif "month" in unit:
            freq = RecurrenceFrequency.MONTHLY
        elif "year" in unit:
            freq = RecurrenceFrequency.YEARLY

    if freq is None:
        if re.search(r"\bevery\s+day\b|\bdaily\b", normalized, re.I):
            freq = RecurrenceFrequency.DAILY
        elif re.search(r"\bevery\s+week\b|\bweekly\b|\bper\s+week\b", normalized, re.I):
            freq = RecurrenceFrequency.WEEKLY
        elif re.search(r"\bevery\s+month\b|\bmonthly\b", normalized, re.I):
            freq = RecurrenceFrequency.MONTHLY
        elif re.search(r"\bevery\s+year\b|\byearly\b|\bper\s+year\b", normalized, re.I):
            freq = RecurrenceFrequency.YEARLY

    # Special case: "once per year"
    if freq is None and re.search(r"\bonce\s+per\s+year\b", normalized, re.I):
        freq = RecurrenceFrequency.YEARLY

    # Default: if a weekday is specified, assume weekly; otherwise daily is too aggressive.
    if freq is None:
        freq = RecurrenceFrequency.WEEKLY if weekdays else RecurrenceFrequency.DAILY

    # Support "3 times per week"
    count_per_period = None
    m_count_week = re.search(r"\b(\d+)\s*(x|times)\s*(per\s*)?week\b", normalized, re.I)
    if m_count_week:
        count_per_period = int(m_count_week.group(1))
        freq = RecurrenceFrequency.WEEKLY

    # Time-of-day window for task series
    tod_window = _detect_time_of_day_window(normalized) if entity_kind == "task_series" else None

    # Start date default: today (in calendar timezone later); keep date anchor.
    start_date = now.date()

    preset = RecurrencePreset(
        frequency=freq,
        interval=interval,
        by_weekday=weekdays if (freq == RecurrenceFrequency.WEEKLY and weekdays and count_per_period is None) else None,
        count_per_period=count_per_period,
        time_start=(time_range[0] if time_range else (weekday_time if weekday_time else None)) if entity_kind == "time_block" else None,
        time_end=(time_range[1] if time_range else None) if entity_kind == "time_block" else None,
        time_of_day_window=tod_window,
        start_date=start_date,
        until_date=None,
    )

    # Validate that time blocks have enough info.
    if entity_kind == "time_block":
        if preset.time_start is None:
            raise RecurrenceParseError("Time block needs a start time", missing=["time_start"])
        # If we only got a single time (weekday+time), require a duration or end time later.
        # MVP default: 60 minutes if end isn't provided.
        if preset.time_end is None:
            if duration_min:
                end_dt = datetime.combine(now.date(), preset.time_start) + timedelta(minutes=int(duration_min))
                preset = preset.model_copy(update={"time_end": end_dt.time()})
            else:
                preset = preset.model_copy(
                    update={"time_end": time(hour=(preset.time_start.hour + 1) % 24, minute=preset.time_start.minute)}
                )

        # Weekly time block should include by_weekday if not daily range.
        if freq == RecurrenceFrequency.WEEKLY and (preset.by_weekday is None or not preset.by_weekday):
            if not weekdays:
                raise RecurrenceParseError("Weekly time block needs a weekday", missing=["by_weekday"])
            preset = preset.model_copy(update={"by_weekday": weekdays})

    return ParsedCapture(entity_kind=entity_kind, title=title, preset=preset, ai_excluded=ai_excluded)

