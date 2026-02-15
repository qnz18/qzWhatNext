"""Tests for recurrence materialization (habit, non-accumulating default)."""

import pytest
from datetime import datetime, timedelta, time as dtime

from qzwhatnext.database.repository import TaskRepository
from qzwhatnext.database.recurring_task_series_repository import RecurringTaskSeriesRepository
from qzwhatnext.recurrence.materialize import materialize_recurring_tasks
from qzwhatnext.models.task import TaskStatus, TaskCategory
from qzwhatnext.models.recurrence import RecurrenceFrequency, RecurrencePreset, TimeOfDayWindow
from qzwhatnext.models.task_factory import create_task_base


def _recurrence_preset_daily_morning():
    return {
        "frequency": RecurrenceFrequency.DAILY.value,
        "interval": 1,
        "time_of_day_window": TimeOfDayWindow.MORNING.value,
        "start_date": None,
        "until_date": None,
    }


@pytest.fixture
def series_repo(db_session):
    return RecurringTaskSeriesRepository(db_session)


@pytest.fixture
def task_repo(db_session):
    return TaskRepository(db_session)


class TestMaterializeHabit:
    """Habit (non-accumulating): at most one open per series; past-window marked missed."""

    def test_past_window_open_marked_missed(
        self, db_session, series_repo, task_repo, test_user_id
    ):
        """Open recurrence task whose flexibility_window has passed is marked missed on materialize."""
        series = series_repo.create(
            user_id=test_user_id,
            title_template="Habit",
            notes_template=None,
            estimated_duration_min_default=15,
            category_default=TaskCategory.HEALTH.value,
            recurrence_preset=_recurrence_preset_daily_morning(),
            ai_excluded=False,
        )
        # Task for "yesterday morning" (window already passed)
        yesterday = datetime.utcnow().date() - timedelta(days=1)
        win_start = datetime.combine(yesterday, dtime(6, 30))
        win_end = datetime.combine(yesterday, dtime(11, 0))
        task = create_task_base(
            user_id=test_user_id,
            source_type="recurrence",
            source_id=series.id,
            title="Habit",
            notes=None,
            estimated_duration_min=15,
            category=TaskCategory.HEALTH,
            ai_excluded=False,
            flexibility_window=(win_start, win_end),
        ).model_copy(
            update={
                "recurrence_series_id": series.id,
                "recurrence_occurrence_start": datetime.combine(yesterday, dtime(0, 0)),
            }
        )
        task_repo.create(task)
        # Materialize with window starting tomorrow so "yesterday" is past
        today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        window_start_tomorrow = today_start + timedelta(days=1)
        window_end_week = today_start + timedelta(days=8)
        materialize_recurring_tasks(
            db_session,
            user_id=test_user_id,
            window_start=window_start_tomorrow,
            window_end=window_end_week,
        )
        updated = task_repo.get(test_user_id, task.id)
        assert updated is not None
        assert updated.status == TaskStatus.MISSED

    def test_at_most_one_open_per_series(
        self, db_session, series_repo, task_repo, test_user_id
    ):
        """Habit: materialize creates only one occurrence per series; second run creates none."""
        series = series_repo.create(
            user_id=test_user_id,
            title_template="Morning routine",
            notes_template=None,
            estimated_duration_min_default=15,
            category_default=TaskCategory.PERSONAL.value,
            recurrence_preset=_recurrence_preset_daily_morning(),
            ai_excluded=False,
        )
        start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        window_start = start
        window_end = start + timedelta(days=7)
        n1 = materialize_recurring_tasks(
            db_session,
            user_id=test_user_id,
            window_start=window_start,
            window_end=window_end,
        )
        assert n1 == 1
        open_tasks = task_repo.get_open_tasks_for_recurrence_series(test_user_id, series.id)
        assert len(open_tasks) == 1
        # Second materialize: series already has open → create nothing
        n2 = materialize_recurring_tasks(
            db_session,
            user_id=test_user_id,
            window_start=window_start,
            window_end=window_end,
        )
        assert n2 == 0
        open_tasks2 = task_repo.get_open_tasks_for_recurrence_series(test_user_id, series.id)
        assert len(open_tasks2) == 1
