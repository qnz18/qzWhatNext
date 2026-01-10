# qzWhatNext – Scoring & Scheduling Engine Spec (v1)

**Version:** 0.1.0  
**Last Updated:** 2025-01-10  
**Status:** Buildable MVP Spec  
**Scope:** Deterministic engine with AI augmentation hooks (non-authoritative)

This document defines the canonical scoring, ranking, and scheduling behavior for **qzWhatNext**.  
It must be consistent with:
- `context-pack.md`
- `decision-log/decisions.md`

---

## 0. Goals

The engine must:
1. Produce a continuously updated **stack-ranked list** of tasks
2. Convert that ranking into a **calendar schedule** that respects constraints
3. Handle overflow by deferring lower-value work and notifying the user
4. Build trust via deterministic behavior, one-line explanations, auditability, and reversibility

**Note:** Transition Time and energy budgeting are deferred to future releases. MVP uses base task durations and schedules based on time availability only.

---

## 1. Definitions

### 1.1 Entity Types

The engine reasons over one schedulable entity type:
- **Task** – user-authored; may be AI-assisted unless excluded

**Note:** Transition Time modeling and task padding are deferred to future releases. MVP uses base task durations only.

---

## 2. Canonical Data Model

### 2.1 Task

A Task has the following fields:

- id: string
- source_type: string (e.g. "google_sheets", "api", "todoist") - metadata only, tasks owned by qzWhatNext
- source_id: string | null (external ID in source system, null for API-created tasks)
- title: string
- notes: string or null
- status: open | completed
- created_at: datetime
- updated_at: datetime
- deadline: datetime or null
- estimated_duration_min: integer
- duration_confidence: float (0–1)
- category: work | child | family | health | personal | ideas | home | admin | unknown
- energy_intensity: low | medium | high
- risk_score: float (0–1)
- impact_score: float (0–1)
- dependencies: list of task IDs
- flexibility_window: (earliest_start, latest_end) or null
- ai_excluded: boolean
- manual_priority_locked: boolean
- user_locked: boolean
- manually_scheduled: boolean

**Task Ownership and Persistence:**
- Tasks are owned by qzWhatNext after import or creation
- All tasks are persisted in database (SQLite for MVP, designed for PostgreSQL migration)
- Source metadata (source_type, source_id) is metadata only, preserved for future bidirectional sync
- Tasks can be created directly via API (source_type="api", source_id=null)
- Source metadata enables deduplication and future bidirectional sync

**Task ID Generation:**
- Task IDs are generated as UUIDs (v4)
- UUIDs ensure global uniqueness and enable distributed systems in future
- Task IDs are immutable once assigned

**Task Duration (MVP):**
- MVP uses base task durations as-is
- Task padding and Transition Time modeling are deferred to future releases

**Note:** `energy_intensity` is included in the Task model but is not used for scheduling decisions in MVP. Energy budgeting is deferred to future releases.

---

### 2.2 Scheduled Block

A ScheduledBlock represents something placed on the calendar:

- id: string
- entity_type: task
- entity_id: string
- start_time: datetime
- end_time: datetime
- scheduled_by: system | user
- locked: boolean
- calendar_event_id: string | null (calendar event ID for sync, null if not synced)

**Note:** MVP schedules tasks only. Explicit Transition entities are deferred to future releases.

---

### 2.4 Audit Event

Audit events capture trust-critical behavior:

- id: string
- timestamp: datetime
- event_type:
  - task_imported
  - task_updated
  - attribute_inferred
  - tier_changed
  - schedule_built
  - schedule_updated
  - snoozed
  - rescheduled
  - completed
  - overflow_flagged
- entity_id: string
- details: object

---

## 3. AI Exclusion Enforcement

A task is **AI-excluded** if:
- its title begins with a period (`.`)
- OR the user explicitly flags it as excluded

AI-excluded tasks:
- are never sent to AI
- never receive AI-updated attributes
- never change tiers due to AI inference
- may still be scheduled deterministically

This rule must be enforced **before any AI call**.

---

## 4. Engine Pipeline

On each rebuild trigger, the engine executes:

1. Ingest and normalize tasks
2. Enforce AI exclusion rules
3. Infer attributes (AI hooks + defaults)
4. Validate hard constraints
5. Assign governing priority tier
6. Score tasks within tier
7. Apply contextual adjustments
8. Construct calendar schedule
9. Detect overflow
10. Generate explanations and audit logs

---

## 5. Rebuild Triggers

A full rebuild occurs when:
- a task is added or imported
- a task is completed
- a task is snoozed or rescheduled
- a user-created calendar event is added or changed (user-blocked time, manually scheduled events)
- the user blocks or unblocks time
- the engine detects schedule invalidation

**Note:** Calendar events created by the system do NOT trigger rebuilds. The system manages tasks first, then updates the calendar. Calendar events are output only in MVP.

Rebuilds must be deterministic given identical inputs.

---

## 6. Attribute Inference (AI Hooks)

### 6.1 Allowed AI Inference

AI may infer, with confidence:
- category
- estimated duration
- duration confidence
- energy intensity
- risk score
- impact score
- dependencies
- transition candidates

AI may **not**:
- assign priority tiers
- override hard constraints
- generate user-facing explanations
- operate on AI-excluded tasks

### 6.2 Defaults (When AI Unavailable)

- duration: 30 minutes
- energy: medium
- category: unknown
- risk: 0.3
- impact: 0.3

---

## 7. Hard Constraints

The schedule must **never violate**:
- user-blocked time
- manually scheduled events
- dependency order
- deadlines
- locked scheduled blocks

If a task cannot be scheduled:
- mark as overflow / unlikely to complete
- notify the user
- never fail silently

---

## 8. Prioritization and Tiering

Each task has exactly **one governing priority tier**.

### 8.1 Fixed Tier Hierarchy (Highest → Lowest)

1. Deadline proximity
2. Risk of negative consequence
3. Downstream impact
4. Child-related needs
5. Personal health needs
6. Work obligations
7. Stress reduction
8. Family/social commitments
9. Home care

### 8.2 Tier Assignment Rules

- AI proposes attributes with confidence
- The rules engine assigns the tier deterministically
- The **highest applicable tier governs**

### 8.3 Tier Change Policy

- High-confidence AI change → apply automatically
- Low-confidence AI change → require user confirmation
- AI-excluded tasks never auto-change tier

All tier changes are logged and explained.

---

## 9. Intra-Tier Scoring

Within a tier, tasks are ordered by a deterministic score derived from:
- deadline urgency
- risk score
- impact score
- dependency unlock value
- fragmentation penalty

Exact coefficients are configurable; v1 favors stability over optimization.

---

## 10. Contextual Adjustments

Within-tier ordering may be adjusted based on:
- duration fit to available blocks
- energy balance
- task flexibility
- recent snooze/reschedule behavior

Contextual adjustments **may not move tasks across tiers**.

---

## 11. Energy Budgeting (Future)

Energy budgeting (daily capacity, energy intensity enforcement) is deferred to future releases. MVP schedules based on time availability only.

---

## 12. Task Duration (MVP)

### 12.1 Definition

MVP uses base task durations as-is. No padding or Transition Time modeling in MVP.

**Duration Usage:**
- Tasks use their estimated_duration_min field directly
- Durations may be AI-estimated via OpenAI API (see D-035) or manually specified
- AI-estimated durations are rounded to 15-minute increments and bounded between 5-600 minutes
- No padding applied
- No Transition Time entities
- Simplest possible MVP scope

**Duration Estimation (Optional):**
- When tasks are created via `/tasks/add_smart` endpoint, duration may be automatically estimated from notes
- Estimation uses confidence threshold (0.6) - only high-confidence estimates are used
- Falls back to default 30 minutes if estimation fails or confidence is too low
- Respects AI exclusion rules (no estimation for excluded tasks)

### 12.2 Future: Task Padding and Transition Time

Task padding percentage and explicit Transition Time modeling (entities, types, rules) are deferred to future releases.

---

## 13. Scheduling Algorithm

The scheduler:
1. iterates tasks in final stack-rank order
2. finds the earliest feasible placement
3. splits tasks into 30-minute minimum chunks if needed
4. marks tasks overflow if no valid placement exists

---

## 14. Overflow Handling

A task is overflow if:
- no valid time block exists
- deadline cannot be met

Overflow behavior:
- surface task to user
- provide one-line reason
- allow manual reprioritization

**Note:** Energy capacity checks are deferred to future releases.

---

## 15. Task Rescheduling (MVP)

MVP supports manual task rescheduling by users. Automatic snooze suggestions are deferred to future releases.

---

## 16. Explainability

Every decision must produce a **one-line explanation** derived from structured reasons.

Examples:
- “Scheduled now due to near deadline and high child-care impact.”
- "Deferred due to insufficient time availability and lower relative importance."

No free-form AI explanations are allowed in v1.

---

## 17. Audit Logging

The engine must log:
- task import and updates
- AI inferences (with confidence)
- tier assignments and changes
- schedule builds
- reschedule actions
- overflow detection

Logs must be queryable for trust and debugging.

---

## 18. MVP Acceptance Criteria

The engine must:
- always produce a stack-ranked list
- respect user-blocked and manual events
- enforce AI exclusion rules
- assign exactly one tier per task
- surface overflow clearly
- explain every decision

---

## 19. Future Compatibility

This v1 spec intentionally supports future capabilities:
- follow-up task chaining
- task padding percentage
- explicit Transition Time modeling (entities, types, rules)
- energy budgeting and capacity management
- smart snooze with automatic suggestions
- automatic duplicate task deduplication
- richer transition inference
- continuous state timelines
- shared tasks with gated feedback
- agentic task execution
- pub/sub automation

None of these are required for MVP.