from __future__ import annotations
from collections import Counter

from .todoist_client import get_tasks
from .categorizer import categorize_task


def main() -> None:
    tasks = get_tasks()
    categorized = [categorize_task(t) for t in tasks]

    # Print summary
    print(f"\n📋 Imported {len(categorized)} tasks from Todoist\n")
    
    # Count by domain
    domain_counts = Counter(t['domain'] for t in categorized)
    print("Tasks by domain:")
    for domain, count in domain_counts.most_common():
        print(f"  {domain}: {count}")
    
    # Count by urgency
    urgency_counts = Counter(t['urgency'] for t in categorized)
    print("\nTasks by urgency:")
    for urgency, count in urgency_counts.most_common():
        print(f"  {urgency}: {count}")
    
    # Print all tasks
    print(f"\n{'='*80}")
    print("All Tasks:")
    print(f"{'='*80}\n")
    
    for t in categorized:
        print(
            f"[{t['domain']}] {t['content']} "
            f"(urgency={t['urgency']}, effort={t['effort']}, impact={t['impact']})"
        )


if __name__ == "__main__":
    main()