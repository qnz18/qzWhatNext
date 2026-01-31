"""Export RecurrencePreset to iCalendar RRULE strings (export-only)."""

from __future__ import annotations

from datetime import date
from typing import List

from qzwhatnext.models.recurrence import RecurrenceFrequency, RecurrencePreset, Weekday


_WD_MAP: dict[Weekday, str] = {
    Weekday.MO: "MO",
    Weekday.TU: "TU",
    Weekday.WE: "WE",
    Weekday.TH: "TH",
    Weekday.FR: "FR",
    Weekday.SA: "SA",
    Weekday.SU: "SU",
}


def preset_to_rrule(p: RecurrencePreset) -> str:
    """Convert preset to an RRULE (without the leading 'RRULE:' prefix)."""
    parts: List[str] = []
    freq = {
        RecurrenceFrequency.DAILY: "DAILY",
        RecurrenceFrequency.WEEKLY: "WEEKLY",
        RecurrenceFrequency.MONTHLY: "MONTHLY",
        RecurrenceFrequency.YEARLY: "YEARLY",
    }[p.frequency]
    parts.append(f"FREQ={freq}")
    if p.interval and int(p.interval) != 1:
        parts.append(f"INTERVAL={int(p.interval)}")
    if p.by_weekday:
        parts.append("BYDAY=" + ",".join(_WD_MAP[d] for d in p.by_weekday))
    # UNTIL: keep date-only to avoid timezone drift; Calendar interprets as end of day in UTC.
    if p.until_date:
        until: date = p.until_date
        parts.append(f"UNTIL={until.strftime('%Y%m%d')}T235959Z")
    return ";".join(parts)

