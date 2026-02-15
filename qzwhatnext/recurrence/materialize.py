"""Materialize recurring task series into concrete Task instances."""

from __future__ import annotations

from datetime import date, datetime, timedelta, time as dtime
from typing import Iterable, List, Optional

from sqlalchemy.orm import Session

from qzwhatnext.database.recurring_task_series_repository import RecurringTaskSeriesRepository
from qzwhatnext.database.repository import TaskRepository
from qzwhatnext.models.recurrence import RecurrenceFrequency, RecurrencePreset, TimeOfDayWindow, Weekday
from qzwhatnext.models.task import TaskCategory, TaskStatus
from qzwhatnext.models.task_factory import create_task_base


def _weekday_enum(d: date) -> Weekday:
    # Python weekday: Monday=0 ... Sunday=6
    idx = d.weekday()
    return [Weekday.MO, Weekday.TU, Weekday.WE, Weekday.TH, Weekday.FR, Weekday.SA, Weekday.SU][idx]


def _daterange(start: date, end_exclusive: date) -> Iterable[date]:
    cur = start
    while cur < end_exclusive:
        yield cur
        cur = cur + timedelta(days=1)


_WINDOWS: dict[TimeOfDayWindow, tuple[dtime, dtime]] = {
    TimeOfDayWindow.WAKE_UP: (dtime(5, 0), dtime(6, 30)),
    TimeOfDayWindow.MORNING: (dtime(6, 30), dtime(11, 0)),
    TimeOfDayWindow.AFTERNOON: (dtime(11, 0), dtime(17, 0)),
    TimeOfDayWindow.EVENING: (dtime(17, 0), dtime(21, 0)),
    TimeOfDayWindow.NIGHT: (dtime(21, 0), dtime(2, 0)),  # spans midnight
}


def _flexibility_window_for_day(day: date, window: TimeOfDayWindow) -> tuple[datetime, datetime]:
    start_t, end_t = _WINDOWS[window]
    start_dt = datetime.combine(day, start_t)
    end_dt = datetime.combine(day, end_t)
    if end_t <= start_t:
        end_dt = end_dt + timedelta(days=1)
    return (start_dt, end_dt)


def _occurs_on_day(p: RecurrencePreset, day: date) -> bool:
    # Respect start/until bounds
    if p.start_date and day < p.start_date:
        return False
    if p.until_date and day > p.until_date:
        return False

    if p.frequency == RecurrenceFrequency.DAILY:
        # Every N days from start_date (or today anchor)
        anchor = p.start_date or day
        delta = (day - anchor).days
        return delta >= 0 and (delta % p.interval == 0)

    if p.frequency == RecurrenceFrequency.WEEKLY:
        anchor = p.start_date or day
        week_delta = (day - anchor).days // 7
        if week_delta < 0 or (week_delta % p.interval != 0):
            return False
        if p.by_weekday:
            return _weekday_enum(day) in p.by_weekday
        return True

    if p.frequency == RecurrenceFrequency.MONTHLY:
        anchor = p.start_date or day
        # Occur on the same day-of-month as anchor.
        if day.day != anchor.day:
            return False
        months = (day.year - anchor.year) * 12 + (day.month - anchor.month)
        return months >= 0 and (months % p.interval == 0)

    if p.frequency == RecurrenceFrequency.YEARLY:
        anchor = p.start_date or day
        if (day.month, day.day) != (anchor.month, anchor.day):
            return False
        years = day.year - anchor.year
        return years >= 0 and (years % p.interval == 0)

    return False


def _choose_n_days_in_week(days: List[date], n: int) -> List[date]:
    """Pick N days from a list, spread deterministically."""
    if n <= 0:
        return []
    if len(days) <= n:
        return days
    # Spread by taking evenly spaced indices.
    step = (len(days) - 1) / float(n - 1) if n > 1 else 0.0
    picks: List[date] = []
    used = set()
    for i in range(n):
        idx = int(round(i * step)) if n > 1 else 0
        idx = max(0, min(idx, len(days) - 1))
        d = days[idx]
        if d in used:
            # Resolve collisions by scanning forward.
            j = idx
            while j < len(days) and days[j] in used:
                j += 1
            if j >= len(days):
                j = idx
                while j >= 0 and days[j] in used:
                    j -= 1
            if j >= 0 and j < len(days):
                d = days[j]
        used.add(d)
        picks.append(d)
    picks.sort()
    return picks


def materialize_recurring_tasks(
    db: Session,
    *,
    user_id: str,
    window_start: datetime,
    window_end: datetime,
) -> int:
    """Create missing Task instances for recurring series within [window_start, window_end).

    Default is habit (non-accumulating): at most one open occurrence per series; past-window
    open occurrences are marked missed and we only materialize the next occurrence.
    Returns number of tasks created.
    """
    series_repo = RecurringTaskSeriesRepository(db)
    task_repo = TaskRepository(db)
    series_rows = series_repo.list_active(user_id)

    # Habit roll-forward: mark open recurrence tasks whose window has passed as missed.
    past_window = task_repo.get_open_recurrence_tasks_with_window_before(user_id, window_start)
    now = datetime.utcnow()
    for t in past_window:
        try:
            task_repo.update(t.model_copy(update={"status": TaskStatus.MISSED, "updated_at": now}))
        except Exception:
            continue

    created = 0
    start_day = window_start.date()
    end_day = window_end.date()

    for s in series_rows:
        p = RecurrencePreset.model_validate(s.recurrence_preset)

        # Habit (non-accumulating): at most one open occurrence per series.
        if task_repo.get_open_tasks_for_recurrence_series(user_id, s.id):
            continue

        # If the series specifies "N times per week", we materialize N occurrences per week
        # inside the window by choosing N days deterministically.
        if p.frequency == RecurrenceFrequency.WEEKLY and p.count_per_period:
            # Group days in window by ISO week.
            week_map: dict[tuple[int, int], List[date]] = {}
            for day in _daterange(start_day, end_day):
                if p.start_date and day < p.start_date:
                    continue
                if p.until_date and day > p.until_date:
                    continue
                # Only consider days in the active weeks (interval)
                anchor = p.start_date or start_day
                week_delta = (day - anchor).days // 7
                if week_delta < 0 or (week_delta % p.interval != 0):
                    continue
                year, week, _ = day.isocalendar()
                week_map.setdefault((year, week), []).append(day)

            # Habit: only the next occurrence (first week in window, first chosen day).
            for _, days in sorted(week_map.items()):
                days.sort()
                chosen_days = _choose_n_days_in_week(days, int(p.count_per_period))
                for day in chosen_days:
                    occ_start = datetime.combine(day, dtime(0, 0))
                    task = create_task_base(
                        user_id=user_id,
                        source_type="recurrence",
                        source_id=s.id,
                        title=s.title_template,
                        notes=s.notes_template,
                        estimated_duration_min=s.estimated_duration_min_default,
                        category=TaskCategory(s.category_default),
                        ai_excluded=bool(s.ai_excluded),
                        flexibility_window=_flexibility_window_for_day(day, p.time_of_day_window)
                        if p.time_of_day_window
                        else None,
                    ).model_copy(
                        update={
                            "recurrence_series_id": s.id,
                            "recurrence_occurrence_start": occ_start,
                        }
                    )
                    try:
                        task_repo.create(task)
                        created += 1
                    except Exception:
                        pass
                    break  # habit: one occurrence per series
                break  # habit: one occurrence per series
            continue

        # Otherwise, use occurs-on-day evaluation. Habit: only the next occurrence (first matching day).
        for day in _daterange(start_day, end_day):
            if not _occurs_on_day(p, day):
                continue
            occ_start = datetime.combine(day, dtime(0, 0))
            task = create_task_base(
                user_id=user_id,
                source_type="recurrence",
                source_id=s.id,
                title=s.title_template,
                notes=s.notes_template,
                estimated_duration_min=s.estimated_duration_min_default,
                category=TaskCategory(s.category_default),
                ai_excluded=bool(s.ai_excluded),
                flexibility_window=_flexibility_window_for_day(day, p.time_of_day_window)
                if p.time_of_day_window
                else None,
            ).model_copy(
                update={
                    "recurrence_series_id": s.id,
                    "recurrence_occurrence_start": occ_start,
                }
            )
            try:
                task_repo.create(task)
                created += 1
            except Exception:
                pass
            break  # habit: one occurrence per series

    return created

