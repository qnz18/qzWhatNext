# qzWhatNext – Decision Log

Version: 0.1.0  
Last Updated: 2025-01-XX  
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
Any task whose title begins with a period (`.`) is always excluded from AI reasoning.

**Rationale:**  
Provides a fast, explicit, user-controlled privacy and trust mechanism.

**Implications:**  
- No AI inference
- No automatic reclassification
- No automatic tier changes
- Task still participates in deterministic scheduling

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
- Required for "last write wins" calendar sync strategy

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
- Calendar sync is one-way: system → calendar (MVP)
- Future bidirectional sync will have separate mechanisms

**Status:** Locked

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

## Canonical Rule

If a future behavior conflicts with a decision in this log:
- The log must be updated explicitly
- Silent divergence is not allowed