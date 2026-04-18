"""Tests for AI temporal inference (deadline / start_after / due_by)."""

from datetime import date, datetime, timezone
from unittest.mock import MagicMock, patch

from qzwhatnext.engine.inference import infer_temporal_fields_for_task
from qzwhatnext.models.task import Task
from qzwhatnext.models.task_factory import create_task_base


def _minimal_task(**kwargs) -> Task:
    t = create_task_base(
        user_id="u1",
        source_type="api",
        source_id=None,
        title="T",
        notes="do something",
        ai_excluded=False,
    )
    for k, v in kwargs.items():
        setattr(t, k, v)
    return t


def test_conflict_start_after_after_due_by_drops_start_after():
    """When model returns start_after > due_by, inference drops start_after only."""
    task = _minimal_task()
    anchor = datetime(2026, 4, 1, 12, 0, 0, tzinfo=timezone.utc)

    raw = {
        "deadline": None,
        "start_after": "2026-06-15",
        "due_by": "2026-06-01",
        "deadline_confidence": 0.0,
        "start_after_confidence": 0.9,
        "due_by_confidence": 0.9,
    }

    with patch("qzwhatnext.engine.inference._get_openai_client") as m:
        client = MagicMock()
        client.infer_temporal_fields.return_value = raw
        m.return_value = client

        dln, sa, db = infer_temporal_fields_for_task(
            task, anchor_utc=anchor.replace(tzinfo=None), time_zone="UTC"
        )

    assert dln is None
    assert sa is None
    assert db == date(2026, 6, 1)


def test_happy_path_applies_all_three():
    task = _minimal_task()
    anchor = datetime(2026, 4, 1, 12, 0, 0)

    raw = {
        "deadline": "2026-05-10T17:00:00Z",
        "start_after": "2026-05-01",
        "due_by": "2026-05-09",
        "deadline_confidence": 0.85,
        "start_after_confidence": 0.85,
        "due_by_confidence": 0.85,
    }

    with patch("qzwhatnext.engine.inference._get_openai_client") as m:
        client = MagicMock()
        client.infer_temporal_fields.return_value = raw
        m.return_value = client

        dln, sa, db = infer_temporal_fields_for_task(
            task, anchor_utc=anchor, time_zone="UTC"
        )

    assert dln is not None
    assert sa == date(2026, 5, 1)
    assert db == date(2026, 5, 9)


def test_ai_excluded_returns_none():
    task = _minimal_task(ai_excluded=True)
    anchor = datetime(2026, 4, 1, 12, 0, 0)

    with patch("qzwhatnext.engine.inference._get_openai_client") as m:
        dln, sa, db = infer_temporal_fields_for_task(task, anchor_utc=anchor, time_zone="UTC")

    assert dln is None and sa is None and db is None
    m.assert_not_called()
