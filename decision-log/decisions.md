# qzWhatNext – Decision Log

Version: 0.1.1  
Last Updated: 2026-01-17  
Status: Locked (MVP decisions)

This log records all non-obvious product and engine decisions that govern qzWhatNext.
If a behavior is questioned, changed, or debugged, this log is the first reference.

---

## D-001 — Product Name

**Decision:**  
The product name is **qzWhatNext**.

**Rationale:**  
Name reflects the core value: telling the user what to do now and next.

**Implications:**  
Used consistently across documentation, code, and AI context.

**Status:** Locked

---

## D-002 — Core Product Characteristic: Trust

**Decision:**  
Continually building **user trust** is a first-class product requirement.

**Rationale:**  
Automation without trust leads to abandonment. Predictability, explainability, and user control are required for adoption.

**Implications:**  
- Deterministic rules override AI
- Explanations are mandatory
- Surprising behavior is avoided even if suboptimal

**Status:** Locked

---

## D-003 — Deterministic Rules Override AI

**Decision:**  
Deterministic engine rules always override AI inference or suggestions.

**Rationale:**  
Ensures predictability, auditability, and safety.

**Implications:**  
AI may assist with inference but never controls outcomes.

**Status:** Locked

---

## D-004 — AI Exclusion via Task Name Prefix

**Decision:**  
Any task whose title or notes field begins with a period (`.`) is always excluded from AI reasoning.

**Rationale:**  
Provides a fast, explicit, user-controlled privacy and trust mechanism. Notes field is checked because tasks created via `/tasks/add_smart` have auto-generated titles, so exclusion must be determined from notes.

**Implications:**  
- No AI inference (category, title, duration, etc.)
- No automatic reclassification
- No automatic tier changes
- Task still participates in deterministic scheduling
- AI exclusion is checked BEFORE any OpenAI API calls (trust-critical)

**Status:** Locked

---

## D-005 — Explicit AI Exclusion Flag

**Decision:**  
Users may explicitly flag any task as AI-excluded.

**Rationale:**  
Supports sensitive or personal tasks where automation is undesirable.

**Implications:**  
Same behavior as `.`-prefixed tasks.

**Status:** Locked

---

## D-006 — Single Governing Priority Tier per Task

**Decision:**  
Each task has exactly **one governing priority tier** at any moment.

**Rationale:**  
Multiple governing tiers would make ranking, scheduling, and explanations ambiguous.

**Implications:**  
Tasks may have multiple signals, but the highest-priority applicable tier governs.

**Status:** Locked

---

## D-007 — Fixed Priority Hierarchy

**Decision:**  
The governing priority hierarchy is fixed and ordered:

1. Deadline proximity  
2. Risk of negative consequence  
3. Downstream impact  
4. Child-related needs  
5. Personal health needs  
6. Work obligations  
7. Stress reduction  
8. Family/social commitments  
9. Home care

**Rationale:**  
A fixed hierarchy ensures predictability and user trust.

**Implications:**  
AI and personalization may not reorder this hierarchy.

**Status:** Locked

---

## D-008 — AI Proposes Attributes, Engine Assigns Tier

**Decision:**  
AI may propose task attributes with confidence; the rules engine assigns the governing tier deterministically.

**Rationale:**  
Separates probabilistic inference from authoritative decision-making.

**Implications:**  
Tier assignment is inspectable and debuggable.

**Status:** Locked

---

## D-009 — Tier Change Policy Based on Confidence

**Decision:**  
Tier changes require user confirmation **only when AI confidence is low**.

**Rationale:**  
Allows self-correction without unnecessary friction or trust erosion.

**Implications:**  
- High-confidence changes apply automatically with explanation
- Low-confidence changes require accept/reject
- Rejected changes inform learning

**Status:** Locked

---

## D-010 — Transition Time Is Not a Task Category (Future)

**Decision:**  
Transition Time is a system-generated, schedulable entity but **not a normal task**. Deferred to future releases.

**Rationale:**  
Transition Time is real but must never compete with tasks or be deprioritized.

**Implications:**  
- Not stack-ranked
- Not snoozable
- Not optional
- Visible and explainable

**Status:** Locked (Future)

---

## D-011 — Transition Time Is First-Class (Future)

**Decision:**  
Transition Time must be explicitly modeled and scheduled. Deferred to future releases; MVP uses task padding instead.

**Examples:**  
- Changing clothes  
- Driving  
- Setup/teardown  
- Waiting  

**Rationale:**  
Eliminates hidden or "phantom" time and improves schedule realism.

**Implications:**  
Consumes time and energy; affects capacity and overflow.

**Status:** Locked (Future)

---

## D-012 — User Overrides for Transition Rules (Future)

**Decision:**  
Users may define plain-English rules that influence Transition Time. Deferred to future releases.

**Rationale:**  
Users know their routines better than any model.

**Implications:**  
Rules are persisted, applied consistently, and editable.

**Status:** Locked (Future)

---

## D-013 — Scheduling Authority Limits

**Decision:**  
The system may move only tasks it scheduled itself.

**May not move:**  
- User-blocked calendar time  
- Manually scheduled events

**Rationale:**  
Protects user intent and trust.

**Status:** Locked

---

## D-014 — Default Scheduling Granularity

**Decision:**  
Default scheduling unit is **30 minutes**.

**Rationale:**  
Balances realism with flexibility.

**Status:** Locked

---

## D-015 — Task Splitting Allowed

**Decision:**  
Tasks may be split across multiple time blocks.

**Rationale:**  
Reflects real-world work patterns and prevents artificial blocking.

**Status:** Locked

---

## D-016 — Energy Budgeting Is Enforced (Future)

**Decision:**  
Each day has a finite energy budget that constrains scheduling. Deferred to future releases.

**Rationale:**  
Time availability alone is insufficient for realistic planning, but energy budgeting adds complexity that can be deferred for MVP.

**Implications:**  
High-energy clustering is avoided; overflow is deferred.

**Status:** Locked (Future)

---

## D-017 — Overflow Handling

**Decision:**  
When work exceeds capacity:
- Protect high-importance tasks
- Defer lower-tier tasks
- Notify the user of likely non-completion

**Rationale:**  
Prevents silent failure and burnout.

**Status:** Locked

---

## D-018 — Smart Snooze Behavior (Future)

**Decision:**  
Snoozing suggests exactly **one** next-best time. Deferred to future releases.

**Triggers:**  
- Missed task  
- Explicit request  
- Detected overload  

**Rationale:**  
Reduces decision fatigue, but adds complexity that can be deferred for MVP.

**Implications:**  
- MVP: Users can manually reschedule tasks
- Future: Automatic snooze suggestions with one recommended time

**Status:** Locked (Future)

---

## D-019 — No Free-Form AI Explanations (v1)

**Decision:**  
User-facing explanations must be generated from templates using structured reasons.

**Rationale:**  
Prevents hallucination, inconsistency, and false certainty.

**Implications:**  
LLMs may not generate open-ended explanation prose in v1.

**Status:** Locked

---

## D-020 — Success Metric Definition

**Decision:**  
Primary success metric is **total number of tasks completed trending upward**.

**Rationale:**  
Percentage completion is distorted by task inflow.

**Status:** Locked

---

## D-021 — MVP Input Sources

**Decision:**  
MVP supports task import from **Google Sheets** and **REST API endpoints**. Todoist integration is deferred to future releases.

**Rationale:**  
Google Sheets provides flexible import while maintaining simplicity. REST API enables direct task creation (e.g., via iPhone shortcuts). Removing Todoist dependency simplifies MVP scope.

**Implications:**  
- Users can export from Todoist to Google Sheets and import
- API endpoints enable programmatic task creation
- Future integrations (Todoist, Google Tasks, etc.) can be added incrementally

**Status:** Locked

---

## D-022 — Future Task Sharing Model

**Decision:**  
Shared tasks may accept priority feedback from others, but changes apply only after user approval.

**Rationale:**  
Prevents external priority hijacking.

**Status:** Locked (Future)

---

## D-023 — Primary Visualization Is Auto-Maintained Calendar

**Decision:**  
The primary visualization of qzWhatNext is an auto-maintained calendar. The MVP uses Google Calendar, but the architecture supports extensibility to other calendar systems.

**Rationale:**  
Calendar visualization provides familiar, time-bound context that users already understand. Auto-maintenance ensures the schedule stays current without manual intervention.

**Implications:**  
- Schedule is automatically synced to calendar after each rebuild
- Calendar events are created/updated/deleted by the system
- User can view schedule in their preferred calendar application
- Architecture must support multiple calendar backends (MVP: Google Calendar only)

**Status:** Locked

---

## D-024 — Multi-User Authentication via Google Sign-In + JWT

**Decision:**  
MVP authenticates users via Google sign-in (ID token verification) and issues a server-signed JWT for API access.

**Rationale:**  
Google sign-in provides low-friction identity. Server-issued JWTs provide stateless API auth and enable deterministic user scoping for all data access.

**Implications:**  
- All task/schedule reads and writes are scoped by authenticated `user_id`
- JWTs are treated as secrets and are never logged

**Status:** Locked

---

## D-025 — Long-Lived Automation Tokens for iOS Shortcuts

**Decision:**  
The system supports a long-lived, revocable automation token for clients that cannot refresh JWTs, passed via `X-Shortcut-Token`.

**Rationale:**  
iOS Shortcuts and similar automation clients need stable authentication without an interactive OAuth flow on each run.

**Implications:**  
- Store only a hashed token at rest (raw token is shown once)
- Tokens are revocable/rotatable
- Requests authenticated with `X-Shortcut-Token` are treated as fully authenticated for that user
- Never log raw tokens

**Status:** Locked

---

## D-026 — Legacy SQLite Schema Compatibility Patch (MVP)

**Decision:**  
If a legacy SQLite DB exists that predates multi-user support, the system may apply a minimal deterministic schema patch to add missing columns required by the current runtime schema (e.g., `tasks.user_id`).

**Rationale:**  
SQLite `create_all()` does not alter existing tables. Without a minimal patch, the app fails at runtime for existing local MVP users.

**Implications:**  
- Patch must be minimal, deterministic, and reversible by restoring the DB from backup
- Legacy rows missing `user_id` may be claimed for the first authenticated user (MVP convenience)

**Status:** Locked

---

## D-024 — Calendar Extensibility

**Decision:**  
The system architecture supports multiple calendar integrations. MVP includes Google Calendar only; other calendar systems (Apple Calendar, Outlook, etc.) are future capabilities.

**Rationale:**  
Users have diverse calendar preferences. Supporting multiple backends increases adoption while keeping MVP scope manageable.

**Implications:**  
- Calendar integration is abstracted behind an interface
- MVP implementation focuses on Google Calendar
- Future calendar integrations follow the same abstraction pattern

**Status:** Locked

---

## D-025 — Custom UI Scope for MVP

**Decision:**  
MVP includes a simple custom UI (table/list view) for parameter refinement and schedule exploration. Timeline/ribbon visualization is deferred to future releases.

**Rationale:**  
Users need a way to view output and refine prioritization parameters. A simple table/list view is faster to implement than a timeline/ribbon UI while providing essential functionality.

**Implications:**  
- Custom UI displays tasks in chronological list format
- Users can view and edit task metadata (priority, duration, category, etc.)
- Users can see the effect of parameter changes on the schedule
- Timeline/ribbon UI is explicitly out of MVP scope

**Status:** Locked

---

## D-026 — Own Database Architecture

**Decision:**  
qzWhatNext maintains its own database optimized for scheduling and prioritization. MVP uses SQLite; architecture supports easy migration to PostgreSQL for scalability.

**Rationale:**  
Own database provides independence from external systems, enables optimization for scheduling queries, and supports both local (Raspberry Pi) and cloud deployments. SQLite balances simplicity with capability; PostgreSQL migration path supports future growth.

**Implications:**  
- Tasks are persisted, not in-memory
- Database schema optimized for scheduling/prioritization queries
- SQLite suitable for single-user MVP scale
- Architecture allows PostgreSQL migration with minimal code changes (using SQLAlchemy or similar ORM)

**Status:** Locked

---

## D-027 — Task Ownership and Source Metadata

**Decision:**  
After import, tasks are owned by qzWhatNext. Source metadata (source_type and source_id) is preserved for future bidirectional sync capabilities but doesn't control behavior.

**Rationale:**  
Task ownership by qzWhatNext enables full control over scheduling and prioritization. Source metadata preservation supports future bidirectional sync without compromising current functionality.

**Implications:**  
- Tasks can be created directly via API (source_type="api", source_id=null)
- Source metadata tracks origin but doesn't control behavior
- Future bidirectional sync can use source metadata to map changes back
- Tasks are fully functional even if source system is unavailable
- See D-030 for source metadata structure (source_type + source_id)

**Status:** Locked

---

## D-028 — REST API for Task Management

**Decision:**  
MVP includes REST API endpoints for task management (create, read, update, delete), enabling programmatic access and integration with tools like iPhone shortcuts.

**Rationale:**  
API enables direct task creation (beyond import), supports custom integrations, and is required for the custom UI. Basic CRUD operations are essential for MVP functionality.

**Implications:**  
- API endpoints support task creation, viewing, updating, and deletion
- API enables iPhone shortcuts and other programmatic access
- Custom UI consumes API endpoints
- API design supports future enhancements (authentication, versioning, etc.)

**Status:** Locked

---

## D-029 — Calendar Sync Strategy (MVP: Last Write Wins)

**Decision:**  
For MVP, calendar sync uses a "last write wins" strategy. The system tracks calendar event IDs and overwrites user changes on rebuild. The system is the source of truth for scheduling.

**Rationale:**  
Simplifies MVP implementation while maintaining system authority over scheduling. Users can view the calendar, but schedule changes must be made through qzWhatNext to maintain consistency.

**Implications:**  
- System tracks calendar_event_id in ScheduledBlock
- On rebuild, system updates/deletes its own calendar events
- User changes to calendar events are overwritten on next rebuild
- Future bidirectional sync will detect user changes and cascade updates to sequential tasks

**Status:** Locked

**Status update (2026-01-26):** Superseded by D-038.

---

## D-030 — Source Metadata Structure

**Decision:**  
Task source metadata is split into `source_type` (system identifier) and `source_id` (external identifier). This structure enables better deduplication, querying, and future bidirectional sync.

**Rationale:**  
Separating type and ID provides clearer structure and enables future bidirectional sync without data model changes. More flexible than a single source string.

**Implications:**  
- `source_type`: string (e.g., "google_sheets", "api", "todoist")
- `source_id`: string | null (external ID in source system, null for API-created tasks)
- Enables deduplication by (source_type, source_id) pairs
- API-created tasks have `source_type="api"`, `source_id=null`

**Status:** Locked

---

## D-031 — Calendar Event ID Tracking

**Decision:**  
ScheduledBlock model includes `calendar_event_id` field to track the calendar event created for that scheduled block.

**Rationale:**  
Enables system to update or delete calendar events on rebuild, preventing duplicate events and maintaining calendar synchronization.

**Implications:**  
- ScheduledBlock tracks calendar_event_id for each synced calendar event
- System can update/delete events it created
- Required for calendar sync idempotency and safe managed updates (see D-038)

**Status:** Locked

---

## D-032 — Duplicate Task Handling (MVP: Simplified)

**Decision:**  
MVP notifies user of potential duplicate tasks but does not auto-deduplicate. Future releases may include automatic deduplication.

**Rationale:**  
Simplifies MVP scope while still alerting users to potential issues. Automatic deduplication logic can be added based on user feedback.

**Implications:**  
- MVP: User notification when potential duplicates are detected (matching source_type, source_id, title)
- User manually decides how to handle duplicates
- Future: Automatic deduplication with merge/replace options

**Status:** Locked

---

## D-033 — Calendar Events Do Not Trigger Rebuilds

**Decision:**  
Calendar events created by the system do not trigger rebuilds. The system manages tasks first, then updates the calendar. Calendar events are output only in MVP.

**Rationale:**  
Prevents rebuild loops and maintains clear data flow: tasks → schedule → calendar. Calendar is a visualization/output, not an input source for MVP.

**Implications:**  
- System-created calendar events are excluded from rebuild triggers
- Rebuild triggers include: task changes, user-blocked time changes, manually scheduled events (user-created)
- Calendar sync is one-way: system → calendar (MVP) **(superseded by D-038)**
- Future bidirectional sync will have separate mechanisms **(implemented for managed events; see D-038)**

**Status:** Locked

**Status update (2026-01-26):** Superseded in part by D-038.

---

## D-034 — Task Padding and Transition Time (Future)

**Decision:**  
Task padding and explicit Transition Time modeling are deferred to future releases. MVP uses base task durations only.

**Rationale:**  
Further simplifies MVP scope. Transition time considerations (padding or explicit modeling) can be added based on user feedback.

**Implications:**  
- MVP uses base task durations as-is
- Task padding percentage and explicit Transition Time entities are future capabilities
- Simplifies scheduling algorithm and data models for MVP

**Status:** Locked (Future)

---

## D-035 — OpenAI API Integration for AI-Assisted Inference

**Decision:**  
qzWhatNext uses OpenAI API (gpt-4o-mini model) for AI-assisted task attribute inference, specifically for category detection, title generation, and duration estimation via the `/tasks/add_smart` endpoint.

**Rationale:**  
AI inference improves user experience by automatically categorizing tasks, generating readable titles, and estimating durations from notes, reducing manual input while maintaining trust through confidence thresholds and fallback behaviors.

**Implementation Details:**
- **Category Inference**: Infers task category from notes with confidence score (threshold: 0.6)
- **Title Generation**: Generates concise, actionable titles from notes (max 100 characters)
- **Duration Estimation**: Estimates task duration in minutes with constraints:
  - Minimum: 5 minutes
  - Maximum: 600 minutes (10 hours)
  - Rounding: Nearest 15 minutes
  - Confidence threshold: 0.6
- **AI Exclusion**: All inference respects AI exclusion rules (tasks starting with "." or flagged as excluded are never sent to OpenAI)
- **Fallback Behavior**: On API failure or low confidence, uses defaults (UNKNOWN category, truncated notes as title, 30 minutes duration)

**Implications:**  
- Requires `OPENAI_API_KEY` environment variable (optional - graceful degradation if not configured)
- API failures never prevent task creation (fallback to defaults)
- All inference checks AI exclusion BEFORE any API calls (trust-critical)
- Confidence thresholds ensure only high-confidence inferences are used
- Duration constraints ensure realistic scheduling bounds

**Status:** Locked

---

## D-036 — Task Deletion Is Soft Delete by Default (MVP)

**Decision:**  
Task deletion defaults to **soft delete** (set `deleted_at`), with explicit endpoints for **restore** (clear `deleted_at`) and **purge** (permanent deletion).

**Rationale:**  
The system’s trust contract requires actions to be reversible. Soft delete supports user mistakes and makes deletions undoable, while purge remains available for irreversible cleanup.

**Implications:**  
- `DELETE /tasks/{task_id}` performs soft delete
- Soft-deleted tasks are hidden from task reads and scheduling
- Restore endpoints re-activate soft-deleted tasks
- Purge endpoints permanently remove tasks
- ScheduledBlocks referencing deleted/purged tasks must be removed to avoid orphaned schedule entries

**Status:** Locked

---

## D-037 — Google Calendar Sync Uses Per-User OAuth Tokens (MVP)

**Decision:**  
Google Calendar sync uses a **per-user web OAuth flow** and stores the resulting **refresh token encrypted at rest** in the database.

**Rationale:**  
Deployed environments (Cloud Run) cannot rely on server-local browser prompts or local token files. Per-user OAuth ensures each user syncs to their own calendar while keeping credentials protected.

**Implications:**  
- Requires `GOOGLE_OAUTH_CLIENT_SECRET` and `TOKEN_ENCRYPTION_KEY` in production
- `POST /sync-calendar` requires the user to connect their calendar via `/auth/google/calendar/start`
- No `credentials.json` / `token.json` is required (or used) for Google Calendar sync in production
- If tokens are revoked/expired, the user must reconnect

**Status:** Locked

---

## D-038 — Google Calendar Sync Is Idempotent and Bidirectional for Managed Events

**Decision:**  
Google Calendar sync is **idempotent** and **bidirectional** for qzWhatNext-managed events:
- The system **creates or updates** only events it can prove it owns (qzWhatNext-managed events).
- If a user edits a qzWhatNext-managed event in Google Calendar, the change is **imported back into qzWhatNext**.
- If the user changes **date/time** in Google Calendar, qzWhatNext **locks** the corresponding `ScheduledBlock` so schedule rebuilds do not move it unless the user explicitly unlocks it.

**Rationale:**  
Prevents duplicate events, preserves user fixes made directly in Calendar, and keeps qzWhatNext and Google Calendar in sync without violating the trust boundary of editing user-owned events.

**Implications:**  
- qzWhatNext-managed events are identified by private `extendedProperties` (e.g., `qzwhatnext_block_id` and a managed marker) and/or persisted `calendar_event_id`
- The system never edits calendar events that are not marked/identified as qzWhatNext-managed
- Per-block calendar version metadata (e.g., `etag`, `updated`) is tracked to detect calendar-side edits deterministically
- Locked scheduled blocks are preserved across schedule rebuilds
- This supersedes the “last write wins” policy described in D-029 for managed events
**Status:** Locked

---

## D-039 — Unified Google Consent for Web Login (MVP)

**Decision:**  
When configured, the web UI uses a **single Google OAuth consent** to obtain both:
- **Identity** (via `id_token`, verified server-side), and
- **Google Calendar authorization** (via a per-user **refresh token** stored encrypted at rest).

qzWhatNext still issues its own server-signed JWT for API access.

**Rationale:**  
For a calendar-first product, asking users to “log in” and then separately “connect calendar” creates unnecessary friction and feels like duplicative trust asks.

**Implications:**  
- Requires `GOOGLE_OAUTH_CLIENT_SECRET` and `TOKEN_ENCRYPTION_KEY` for unified login+calendar consent.
- If unified consent is not configured, the system falls back to identity-only login and Calendar is connected on demand (existing `/auth/google/calendar/*` flow).
- This supersedes the D-037 implication that Calendar connect must happen only via `/auth/google/calendar/start` for all users; reconnect endpoints remain for recovery/revocation scenarios.

**Status:** Locked

---

## D-040 — Single-Input Recurring Capture (MVP)

**Decision:**  
qzWhatNext supports creating and updating repeating items via a single input endpoint (`POST /capture`). The system deterministically chooses whether the instruction becomes:
- a **Recurring Task Series** (which materializes Task instances into the active scheduling horizon), or
- a **Recurring Time Block** (a recurring Google Calendar event that blocks time).

Additionally, if the instruction includes **one-off anchors** like “this” or “next” (and does **not** include “every”), `/capture` creates a **non-repeating** entity using the same deterministic split:
- explicit time range or weekday+time → a **one-off Calendar event** (reserved time)
- otherwise → a **one-off Task**

Recurring time blocks are created in the user’s **Google Calendar timezone** and are treated as **user-blocked time** (reserved intervals) during schedule builds.

**Rationale:**  
Users should not need to decide “task vs time block” or remember different endpoints. A single capture flow reduces friction while preserving deterministic behavior and clear ownership boundaries in Calendar.

**Implications:**  
- A new `POST /capture` endpoint exists for create/update of recurring capture entities, and create of one-off captured entities.
- Recurring task series generate concrete Task instances, de-duped by `(user_id, recurrence_series_id, recurrence_occurrence_start)`.
- Recurring time blocks are created as recurring Google Calendar events and are **not** marked as qzWhatNext-managed schedule events (so they behave like reserved time).
- AI parsing may be used only when the instruction is not AI-excluded; AI-excluded instructions must never be sent to AI.
**Status:** Draft (MVP)

---

## D-041 — Task Start-After and Due-By (MVP)

**Decision:**  
Tasks may optionally include:
- `start_after` (date): the scheduler must not schedule the task before this date.
- `due_by` (date): a soft due date that increases urgency within the task’s existing tier as the date approaches/passes.

`due_by` affects **within-tier ordering only** and must not move tasks across the fixed tier hierarchy.

**Rationale:**  
This provides a consistent, deterministic way to express “not before X” and “get louder by Y” for any task, without inventing special-case rolling behaviors tied to particular phrases.

**Implications:**  
- The API and DB add `start_after` and `due_by` to Task.
- Scheduling enforces `start_after` as a hard earliest-start constraint.
- Ranking uses `due_by` as a soft urgency signal within tier.
**Status:** Draft (MVP)

---

## D-042 — Adjustable Schedule Horizon (MVP)

**Decision:**  
The schedule build horizon is user-adjustable to one of: **7, 14, or 30 days** (capped at 30).

**Rationale:**  
7 days is often sufficient, but users sometimes need to plan farther out (e.g., coordinating family or social plans). A small set of fixed options preserves determinism and avoids overfitting UX.

**Implications:**  
- `POST /schedule` accepts `horizon_days` (7/14/30).
- Calendar availability queries and scheduling use the same horizon window.
**Status:** Draft (MVP)

---

## D-043 — UI Time Display Uses Calendar Timezone (MVP)

**Decision:**  
The web UI displays all schedule/task timestamps in the user’s **Google Calendar timezone** (IANA tz ID). If the Calendar timezone is not available, the UI falls back to the **browser timezone**.

**Rationale:**  
Users expect schedule times to match what they see in Google Calendar; displaying in the wrong timezone breaks trust and makes planning error-prone.

**Implications:**  
- `POST /schedule` includes a `time_zone` field in its response (best-effort), so the UI can render timestamps correctly.
- If `time_zone` is missing, the UI uses the browser timezone for display.
**Status:** Draft (MVP)

---

## Canonical Rule

If a future behavior conflicts with a decision in this log:
- The log must be updated explicitly
- Silent divergence is not allowed