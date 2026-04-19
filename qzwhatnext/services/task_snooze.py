"""Apply snooze presets by narrowing task flexibility_window and rebuilding the schedule."""

from __future__ import annotations

import logging
from datetime import date, datetime, time, timedelta, timezone
from enum import Enum
from typing import Optional, Tuple

from sqlalchemy.orm import Session
from zoneinfo import ZoneInfo

from qzwhatnext.database.repository import TaskRepository
from qzwhatnext.models.task import Task
from qzwhatnext.services.schedule_calendar import (
    best_effort_rebuild_and_sync,
    config_schedule_horizon_days,
    get_calendar_timezone_for_user_best_effort,
)

logger = logging.getLogger(__name__)


class SnoozePreset(str, Enum):
    """User-facing snooze options; mapped to flexibility windows (sensible defaults)."""

    M15 = "15m"
    H1 = "1h"
    LATER_TODAY = "later_today"
    TONIGHT = "tonight"
    TOMORROW = "tomorrow"


# "Tonight" = evening block local time (defaults; tune via env if needed).
_TONIGHT_START_HOUR = 17
_TONIGHT_END_HOUR = 23
_TONIGHT_END_MINUTE = 59


def _utc_naive(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt
    return dt.astimezone(timezone.utc).replace(tzinfo=None)


def _now_in_tz(utc_now: datetime, tz_name: str) -> datetime:
    try:
        z = ZoneInfo(tz_name)
    except Exception:
        z = ZoneInfo("UTC")
    u = utc_now
    if u.tzinfo is None:
        u = u.replace(tzinfo=timezone.utc)
    return u.astimezone(z)


def _local_day_bounds(d: date, tz_name: str) -> Tuple[datetime, datetime]:
    """Start of local day and end of local day (last microsecond), as timezone-aware in tz."""
    try:
        z = ZoneInfo(tz_name)
    except Exception:
        z = ZoneInfo("UTC")
    start = datetime.combine(d, time(0, 0, 0), tzinfo=z)
    end = datetime.combine(d, time(23, 59, 59, 999999), tzinfo=z)
    return start, end


def compute_snooze_window(
    preset: SnoozePreset,
    *,
    utc_now: datetime,
    horizon_days: int,
    tz_name: str,
) -> Tuple[datetime, datetime]:
    """Return (flexibility_window_start, flexibility_window_end) as UTC-naive datetimes.

    The scheduler requires the full task duration to fit within [start, end).
    Windows are clamped to [utc_now, utc_now + horizon_days).
    """
    if utc_now.tzinfo is not None:
        utc_now = _utc_naive(utc_now)
    schedule_end = utc_now + timedelta(days=min(int(horizon_days), 30))

    now_local = _now_in_tz(utc_now.replace(tzinfo=timezone.utc), tz_name)
    today_local = now_local.date()

    if preset == SnoozePreset.M15:
        w0 = utc_now + timedelta(minutes=15)
        return w0, schedule_end

    if preset == SnoozePreset.H1:
        w0 = utc_now + timedelta(hours=1)
        return w0, schedule_end

    if preset == SnoozePreset.LATER_TODAY:
        _, day_end_local = _local_day_bounds(today_local, tz_name)
        w0 = max(_utc_naive(now_local), utc_now)
        w1 = min(_utc_naive(day_end_local), schedule_end)
        if w1 <= w0:
            w1 = min(w0 + timedelta(hours=1), schedule_end)
        return w0, w1

    if preset == SnoozePreset.TONIGHT:
        day = today_local
        start_local = datetime.combine(day, time(_TONIGHT_START_HOUR, 0, 0), tzinfo=now_local.tzinfo)
        end_local = datetime.combine(day, time(_TONIGHT_END_HOUR, _TONIGHT_END_MINUTE, 59), tzinfo=now_local.tzinfo)
        if now_local > end_local:
            day = today_local + timedelta(days=1)
            start_local = datetime.combine(day, time(_TONIGHT_START_HOUR, 0, 0), tzinfo=now_local.tzinfo)
            end_local = datetime.combine(day, time(_TONIGHT_END_HOUR, _TONIGHT_END_MINUTE, 59), tzinfo=now_local.tzinfo)
        w0 = max(_utc_naive(now_local), _utc_naive(start_local))
        w1 = min(_utc_naive(end_local), schedule_end)
        if w1 <= w0:
            w1 = min(w0 + timedelta(hours=1), schedule_end)
        return w0, w1

    if preset == SnoozePreset.TOMORROW:
        tomorrow = today_local + timedelta(days=1)
        start_l, _ = _local_day_bounds(tomorrow, tz_name)
        _, end_l = _local_day_bounds(tomorrow, tz_name)
        w0 = _utc_naive(start_l)
        w1 = min(_utc_naive(end_l), schedule_end)
        if w1 <= w0:
            w1 = min(w0 + timedelta(hours=2), schedule_end)
        return w0, w1

    w0 = utc_now + timedelta(minutes=15)
    return w0, schedule_end


def apply_snooze_preset(
    db: Session,
    user_id: str,
    task_id: str,
    preset: SnoozePreset,
) -> Task:
    """Set task flexibility_window from preset, update DB, rebuild+sync. Raises ValueError if invalid."""
    repo = TaskRepository(db)
    task = repo.get(user_id, task_id)
    if not task:
        raise ValueError("Task not found")

    if task.status != "open":
        raise ValueError("Only open tasks can be snoozed")

    if getattr(task, "manually_scheduled", False):
        raise ValueError("Manually scheduled tasks cannot be snoozed via this endpoint")

    tz_name = get_calendar_timezone_for_user_best_effort(db, user_id)
    horizon = config_schedule_horizon_days()
    utc_now = datetime.utcnow()

    w0, w1 = compute_snooze_window(preset, utc_now=utc_now, horizon_days=horizon, tz_name=tz_name)

    dur = max(int(task.estimated_duration_min or 30), 1)
    if w0 + timedelta(minutes=dur) > w1:
        logger.info(
            "Snooze window too tight for duration; extending end preset=%s task=%s",
            preset.value,
            task_id,
        )
        w1 = min(w0 + timedelta(minutes=dur + 30), utc_now + timedelta(days=min(horizon, 30)))

    updated = task.model_copy(
        update={
            "flexibility_window": (w0, w1),
            "updated_at": datetime.utcnow(),
        }
    )
    out = repo.update(updated)
    best_effort_rebuild_and_sync(db, user_id)
    return out
