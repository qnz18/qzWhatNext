from __future__ import annotations

from .todoist_client import get_tasks
from .categorizer import categorize_task


def main() -> None:
    tasks = get_tasks()
    categorized = [categorize_task(t) for t in tasks]

    for t in categorized:
        print(
            f"[{t['domain']}] {t['content']} "
            f"(urgency={t['urgency']}, effort={t['effort']}, impact={t['impact']})"
        )


if __name__ == "__main__":
    main()