"""Calendar event description helpers: stable task id footer for HA and integrations."""

from __future__ import annotations

import re
from typing import Optional

TASK_ID_LINE_PATTERN = re.compile(
    r"(?m)^\s*qzwhatnext_task_id:\s*(\S+)\s*$",
)


def append_task_id_footer(description: Optional[str], task_id: str) -> str:
    """Append stable machine line for Google Calendar description (not stored on Task.notes in DB)."""
    base = (description or "").rstrip()
    marker = f"qzwhatnext_task_id:{task_id}"
    if marker in base:
        return base
    if base:
        return f"{base}\n\n{marker}"
    return marker


def strip_task_id_footer(description: Optional[str]) -> str:
    """Remove qzwhatnext_task_id line for comparing imported calendar text to task.notes."""
    if not description:
        return ""
    lines = []
    for line in description.splitlines():
        if line.strip().startswith("qzwhatnext_task_id:"):
            continue
        lines.append(line)
    return "\n".join(lines).strip()


def extract_task_id_from_calendar_text(description: Optional[str]) -> Optional[str]:
    """Parse task id from calendar description footer."""
    if not description:
        return None
    m = TASK_ID_LINE_PATTERN.search(description.strip())
    return m.group(1).strip() if m else None
