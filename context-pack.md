# qzWhatNext – Canonical Context Pack

Version: 0.1.1  
Last Updated: 2026-01-17  
Status: Locked (MVP)

---

## 1. Product Identity

**Product Name:** qzWhatNext  

**Core Purpose:**  
Continuously tell the user what they should be doing **right now** and **immediately next**, across work, children, health, and home responsibilities.

**Primary Characteristic:**  
Continually builds **user trust** through predictability, transparency, explainability, and user control.

**Target User:**  
Busy professionals with children and personal health responsibilities who experience constant task overload and fragmented time.

---

## 2. Core Value Proposition

qzWhatNext:
- Automatically **identifies** tasks across sources
- Continuously **stack-ranks** what matters most
- **Auto-schedules** tasks into real time
- Makes **hidden time and effort visible**
- Adapts over time without surprising the user

Existing tools store tasks; qzWhatNext decides **what to do now and next**.

---

## 3. Non-Negotiables (Global Rules)

These rules apply everywhere in the system.

- Deterministic rules always override AI
- User trust is prioritized over optimization
- User-blocked calendar time is never moved
- Manually scheduled events are never moved
- All system actions must be explainable
- All system actions must be reversible
- No user data is shared with third parties

---

## 3.1 Multi-User and Authentication (MVP)

qzWhatNext is a multi-user system. All persisted data is user-scoped:
- Tasks are owned by exactly one user (via `user_id`)
- Scheduled blocks are owned by exactly one user (via `user_id`)
- All reads/writes must be filtered by the authenticated user

**Authentication (MVP):**
- Primary: Google sign-in → server verifies Google ID token → server issues JWT
- Automation clients (e.g., iOS Shortcuts): long-lived per-user token via `X-Shortcut-Token`

**Security properties:**
- JWTs are short-lived and are used for browser/API sessions
- Shortcut tokens are long-lived and must be revocable; store only hashed tokens at rest

---

## 4. AI Guardrails

### 4.1 AI Exclusion Rules

A task must **always** be excluded from AI reasoning if:
- The task title begins with a period (`.`)
- The user explicitly flags the task as AI-excluded

AI-excluded tasks:
- Are never passed to AI
- Are never reclassified automatically
- Have manually fixed attributes and priority
- May still be scheduled deterministically

This rule exists to preserve privacy and trust.

---

### 4.2 AI Responsibilities (Allowed)

AI may assist with **structured inference only**, including:
- Task category detection
- Task title generation (from notes)
- Duration estimation
- Energy intensity inference
- Risk and impact estimation
- Dependency inference
- Transition Time inference

AI must provide **confidence scores** for inferred attributes.

---

### 4.3 AI Responsibilities (Disallowed)

AI may **not**:
- Directly assign priority tiers
- Override hard constraints
- Move user-blocked or manually scheduled time
- Generate free-form user-facing explanations (v1)
- Use tasks excluded by rule or prefix

---

## 5. Task Model Fundamentals

- A task may have many attributes (deadline, child need, health, work, etc.)
- A task has **one governing priority tier** at any moment
- Supporting attributes influence ordering **within** the tier
- Tier assignment is deterministic, not probabilistic

---

## 6. Prioritization Model

### 6.1 Governing Priority Hierarchy (Fixed)

Tasks are assigned to the **highest applicable tier** based on this fixed hierarchy:

1. Deadline proximity  
2. Risk of negative consequence  
3. Downstream impact  
4. Child-related needs  
5. Personal health needs  
6. Work obligations  
7. Stress-reduction value  
8. Family and social commitments  
9. Home care and maintenance  

This hierarchy is consistent across all users to ensure predictability.

---

### 6.2 Tier Assignment Rules

- AI proposes task attributes with confidence
- The rules engine assigns the governing tier deterministically
- A task may trigger multiple tiers; the **highest-priority tier governs**

---

### 6.3 Tier Changes and Learning

- AI may update task attributes over time
- Attribute updates may change the governing tier

**Tier Change Policy:**
- If AI confidence is **high**, tier changes apply automatically
- If AI confidence is **low**, user confirmation is required
- All tier changes are logged and explained

Tasks excluded from AI (`.` prefix or manual flag) are never re-tiered automatically.

---

## 7. Task Duration (MVP)

MVP uses base task durations as-is. No padding or Transition Time modeling in MVP scope.

---

## 8. Transition Time and Task Padding (Future Concept)

**Note:** Task padding and explicit Transition Time modeling are deferred to future releases.

Future releases will include:
- Task padding percentage (user-configurable, rounded to 15-min increments)
- Explicit Transition entities (system-generated time between tasks)
- Transition types (changing clothes, driving, setup/teardown, etc.)
- User-defined transition rules
- Transition inheritance and constraints

---

## 9. Scheduling Fundamentals

- Default scheduling unit: 30 minutes
- Tasks may be split across blocks
- The system may move tasks it scheduled itself
- The system may not move:
  - User-blocked time
  - Manually scheduled events

When workload exceeds capacity:
- High-importance tasks are protected
- Lower-tier tasks are deferred
- The user is notified of likely overflow

---

## 10. Energy Awareness (Future)

Energy budgeting (energy intensity, daily capacity, clustering rules) is deferred to future releases. MVP schedules based on time availability only.

---

## 11. Task Rescheduling (MVP)

MVP supports manual task rescheduling by users. Automatic snooze suggestions are deferred to future releases.

---

## 12. Explainability (Trust Requirement)

Every system decision must produce a **one-line explanation** derived from structured reasons.

Examples:
- “Scheduled now due to near deadline and high child-care impact.”
- "Deferred due to insufficient time availability and lower relative importance."

No free-form AI explanations are allowed in v1.

---

## 13. Success Metrics (MVP)

Primary:
- Total number of tasks completed trends upward over time

Secondary:
- Snoozing frequency trends downward
- Rescheduling frequency trends downward
- User acceptance of recommendations trends upward

Percentage completion is explicitly excluded.

---

## 14. MVP Scope

Included:
- Task import (Google Sheets, REST API)
- Database persistence (SQLite)
- Multi-user authentication and user-scoped data access
- Google sign-in → JWT for API calls
- Long-lived automation token for iOS Shortcuts (`X-Shortcut-Token`, revocable)
- Automatic task identification
- Continuous stack-ranking
- Auto-scheduling (using base task durations)
- Schedule persistence (scheduled blocks persisted, not in-memory)
- Overflow detection and notification
- Explainable decisions
- Auto-maintained calendar visualization (Google Calendar)
- Simple custom UI (table/list view) for parameter refinement
- REST API for task management

Excluded:
- Task execution
- Timeline/ribbon UI visualization
- Shared tasks

---

## 15. Future State Capabilities (Captured)

- Context-aware follow-up task chaining
- Expanded task capture:
  - Todoist
  - Apple Notes
  - Apple Reminders
  - Google Tasks
  - Google Calendar
  - Google Docs
  - PDFs
- Task sharing with gated priority feedback
- Agentic task execution in third-party apps
- Continuous state machine and life timeline
- Event-driven automation (pub/sub)
- Timeline/ribbon UI visualization
- Additional calendar integrations (Apple Calendar, Outlook, etc.)
- Bidirectional sync to original sources
- Task padding percentage (user-configurable)
- Explicit Transition Time modeling (entities, types, rules)
- Energy budgeting and capacity management
- Smart snooze with automatic suggestions
- Automatic duplicate task deduplication

---

## 16. Canonical Rule

**Chats generate artifacts.  
Artifacts replace chats.**

This document is the canonical context for:
- Custom GPTs
- Cursor
- Documentation
- Ongoing planning and design

If a future idea conflicts with this pack, the pack must be updated explicitly.

---

## 17. Primary Visualization and User Interface

### 16.1 Calendar as Primary Visualization

The primary visualization of qzWhatNext is an **auto-maintained calendar**. The schedule is automatically synced to the user's calendar after each rebuild, ensuring the calendar always reflects the current stack-ranked schedule.

**MVP Implementation:**
- Google Calendar integration
- Automatic event creation, update, and deletion
- Calendar events include task metadata via extended properties
- System uses "last write wins" strategy (system overwrites user changes on rebuild)
- System tracks calendar event IDs to enable update/delete operations

**Future Extensibility:**
- Architecture supports multiple calendar backends
- Additional calendar systems (Apple Calendar, Outlook, etc.) are future capabilities
- Future: Bidirectional sync with cascading updates to sequential tasks

### 16.2 Custom User Interface

A simple custom UI provides essential functionality for viewing and refining the schedule:

**Display Format:*
- Chronological list/table view of scheduled tasks
- Shows tasks in stack-ranked order with time assignments

**Parameter Refinement:**
- View task metadata (priority tier, duration, category, energy intensity, etc.)
- Edit task parameters:
  - Due date override
  - Priority override
  - Stack rank value
  - Duration estimate
  - Category override
- See immediate effect of parameter changes on the schedule

**User Control:**
- Full control over all task parameters when necessary
- Changes trigger schedule rebuild with updated parameters
- All overrides are logged and reversible

**MVP Scope:**
- Simple table/list view (not timeline/ribbon)
- Essential parameter editing capabilities
- Timeline/ribbon visualization is deferred to future releases