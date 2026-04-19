"""Tests for snooze presets and calendar description footers."""

from datetime import datetime

import pytest

from qzwhatnext.services.calendar_event_text import (
    append_task_id_footer,
    extract_task_id_from_calendar_text,
    strip_task_id_footer,
)
from qzwhatnext.services.task_snooze import SnoozePreset, compute_snooze_window


def test_compute_snooze_15m():
    utc = datetime(2026, 1, 1, 12, 0, 0)
    w0, w1 = compute_snooze_window(
        SnoozePreset.M15,
        utc_now=utc,
        horizon_days=7,
        tz_name="America/New_York",
    )
    assert w0 == datetime(2026, 1, 1, 12, 15)
    assert w1 > w0


def test_append_and_extract_task_id():
    tid = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    d = append_task_id_footer("Hello notes", tid)
    assert "Hello notes" in d
    assert extract_task_id_from_calendar_text(d) == tid


def test_strip_task_id_footer():
    tid = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    raw = append_task_id_footer("Notes here", tid)
    assert strip_task_id_footer(raw) == "Notes here"


def test_snooze_preset_enum_values():
    assert SnoozePreset.M15.value == "15m"
    assert SnoozePreset.TOMORROW.value == "tomorrow"


@pytest.mark.parametrize(
    "preset",
    [
        SnoozePreset.M15,
        SnoozePreset.H1,
        SnoozePreset.LATER_TODAY,
        SnoozePreset.TONIGHT,
        SnoozePreset.TOMORROW,
    ],
)
def test_all_presets_produce_ordered_window(preset):
    utc = datetime(2026, 6, 15, 14, 30, 0)
    w0, w1 = compute_snooze_window(
        preset,
        utc_now=utc,
        horizon_days=7,
        tz_name="UTC",
    )
    assert w1 > w0
