# To-Do Orchestrator – MVP Design (Pilot Backend)

## Goal

MVP goal: build a small backend that:

1. Fetches tasks from Todoist (stubbed at first).
2. Categorizes each task along a few dimensions.
3. Guarantees basic invariants via guardrail tests.

This pilot focuses on **rule-based categorization** and **testable behavior**. No calendar or subtask expansion yet.

## Categorization Dimensions (MVP)

Each task should be enriched with:

- `domain`: high-level area
- `urgency`: how soon it needs attention
- `effort`: rough size
- `impact`: rough importance

These are implemented as Python `Literal` types in `app.models`.

## Guardrails

The first test layer is about structural correctness and simple invariants:

- Every categorized task must have:
  - A valid `domain`, `urgency`, `effort`, `impact` value.
- Overdue tasks must not be categorized as `SOMEDAY`.
- No exceptions during categorization for normal tasks.

Later we will add:

- Example-based tests driven by external data.
- Higher-level behavior (e.g., domain detection quality, etc.).