"""High-level interpretation for capture instructions.

This module is the single entrypoint used by the /capture API.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from qzwhatnext.recurrence.deterministic_parser import ParsedCapture, parse_capture_instruction


def interpret_capture_instruction(
    instruction: str,
    *,
    ai_allowed: bool,
    now: Optional[datetime] = None,
) -> ParsedCapture:
    """Interpret a capture instruction.

    Current behavior (Phase 1/2):
    - Deterministic parse is authoritative and must succeed for supported patterns.
    - AI parsing hooks can be added later for broader language coverage, but are never required.
    """
    # Even when AI is allowed, we keep deterministic parsing as the stable baseline.
    # If/when we add an AI parser, it must return the same schema and never run if AI-excluded.
    return parse_capture_instruction(instruction, now=now)

