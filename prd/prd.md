# qzWhatNext – Product Requirements Document (PRD)

**Version:** 0.1.0  
**Last Updated:** 2025-01-XX  
**Status:** MVP Locked  
**Primary Characteristic:** Continually builds user trust

This PRD defines what **qzWhatNext** is, what it does, and what it explicitly does not do for the MVP.  
Behavioral specifics are governed by:
- `context-pack.md`
- `decision-log/decisions.md`
- `engine/scoring-and-scheduling.md`

---

## 1. Problem Statement

Busy professionals balancing work, children, personal health, and home responsibilities face constant cognitive overload. Tasks are fragmented across multiple lists, notes, calendars, and documents. Deciding *what to do now* versus *what comes next* requires continuous manual prioritization and calendar management.

Existing tools can store tasks and events, but they do not:
- Automatically identify task intent, impact, or urgency
- Continuously stack-rank tasks based on what matters most
- Actively manage time, energy, and transitions
- Build trust through transparent, explainable automation

**qzWhatNext** solves this by automatically identifying, stack-ranking, and scheduling tasks into real time—while respecting user constraints, preferences, and privacy.

---

## 2. Target User

**Primary User**
- Busy professional
- Has children
- Manages personal health
- Responsible for work, family, and home care

**Key Characteristics**
- High task inflow
- Fragmented availability
- Strong privacy expectations
- Wants automation with predictability and control

---

## 3. Core Value Proposition

> “Keeps track of everything you have to do across multiple lists, automatically identifies and stack-ranks what matters most, and tells you what you should be doing right now and immediately next.”

---

## 4. Product Principles (Non-Negotiable)

1. Trust over optimization  
2. Deterministic behavior over probabilistic outcomes  
3. Explainability for every system action  
4. User control over sensitive data and decisions  
5. No silent failures  

---

## 5. Goals and Success Metrics

### Primary Metric
- Total number of tasks completed trends upward over time

### Secondary Indicators
- Snoozing frequency trends downward
- Rescheduling frequency trends downward
- User acceptance of recommendations trends upward

### Explicitly Excluded Metrics
- Percentage task completion (distorted by inflow)

---

## 6. MVP Scope

### In Scope
- Task import (Google Sheets, REST API)
- Database persistence (SQLite)
- Automatic task identification and classification
- Continuous stack-ranking of tasks
- Auto-scheduling into calendar free time
- Explicit modeling of Transition Time
- Energy-aware scheduling
- Overflow detection and notification
- One-line explanation for every decision
- Auto-maintained calendar visualization (Google Calendar)
- Simple custom UI (table/list view) for parameter refinement
- REST API for task management

### Out of Scope
- Task execution in third-party apps
- Timeline / ribbon UI visualization
- Task sharing or collaboration
- Automation triggers or pub/sub

---

## 7. Functional Requirements

### 7.1 Task Ingestion

**Import Sources:**
- Import tasks from Google Sheets
- Create tasks directly via REST API endpoints
- Tasks are owned by qzWhatNext after import (source field is metadata only)

**Data Persistence:**
- All tasks are persisted in database (SQLite for MVP)
- Database optimized for scheduling and prioritization queries
- Tasks remain available even if source system is unavailable

**Processing:**
- Normalize tasks into canonical format
- Maintain audit trail of changes
- Source metadata preserved for future bidirectional sync

---

### 7.2 Task Understanding
The system automatically infers:
- Task category
- Estimated duration
- Energy intensity
- Risk of delay
- Downstream impact
- Dependencies

Tasks starting with `.` or explicitly flagged by the user are always excluded from AI reasoning.

---

### 7.3 Prioritization
- Every task has exactly one governing priority tier
- Tier assignment follows a fixed hierarchy
- Tasks are continuously stack-ranked
- AI assists with inference but never assigns priority directly

---

### 7.4 Scheduling
- Default scheduling granularity: 30 minutes
- Tasks may be split across multiple blocks
- The system may move tasks it scheduled itself
- The system may not move:
  - User-blocked time
  - Manually scheduled events

---

### 7.5 Transition Time
- Transition Time is system-generated, not user-authored
- Examples:
  - Changing clothes
  - Driving
  - Setup / teardown
- Transition Time is schedulable, visible, and consumes energy
- Transition Time cannot be snoozed or skipped directly

---

### 7.6 Energy Awareness
- Each task has an energy intensity
- Each day has a finite energy capacity
- High-energy clustering is avoided
- Lower-priority work is deferred when capacity is exceeded

---

### 7.7 Smart Snooze
- Snooze triggers:
  - Missed task
  - Explicit user request
  - Detected overload
- Only one snooze suggestion is provided
- Snoozing avoids deadline violations where possible
- Optional “why” feedback is captured

---

### 7.8 Explainability
Every system decision must include a one-line explanation derived from structured reasons.

Examples:
- "Scheduled now due to near deadline and high child-care impact."
- "Deferred due to energy overload and lower relative importance."

Free-form AI explanations are not allowed in MVP.

---

### 7.9 Custom User Interface

The MVP includes a simple custom UI for viewing and refining the schedule.

**Display Format:**
- Chronological list/table view of scheduled tasks
- Tasks displayed in stack-ranked order with assigned time slots
- Transition time and buffer time explicitly shown

**Parameter Refinement:**
- View task metadata (priority tier, duration, category, energy intensity, risk score, impact score, etc.)
- Edit task parameters:
  - Due date override
  - Priority override
  - Stack rank value
  - Duration estimate
  - Transition details
  - Category override
  - Energy intensity
  - Risk and impact scores
- See immediate effect of parameter changes on the schedule
- Changes trigger automatic schedule rebuild

**User Control:**
- Full control over all task parameters when necessary
- All overrides are logged and reversible
- Changes are reflected immediately in both the custom UI and calendar visualization

**MVP Limitations:**
- Simple table/list view only (not timeline/ribbon visualization)
- Timeline/ribbon UI is deferred to future releases

---

## 8. Failure Handling

- If a schedule becomes invalid, the system rebuilds it deterministically
- If work exceeds capacity:
  - Lower-tier tasks are deferred
  - The user is notified
- No silent task drops are allowed

---

## 9. Privacy and Trust

- No user data is shared with third parties
- Sensitive tasks are supported
- AI-excluded tasks are never passed to AI
- All actions are logged and reversible
- Trust-building behavior takes precedence over efficiency

---

## 10. Future Capabilities (Captured, Not in MVP)

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
- Agentic task execution
- Continuous state machine and timeline
- Pub/sub automation
- Timeline/ribbon UI visualization
- Additional calendar integrations (Apple Calendar, Outlook, etc.)
- Bidirectional sync to original sources

---

## 11. Non-Goals

The MVP will not:
- Replace full project management tools
- Support team task ownership
- Optimize for maximum utilization at the expense of trust
- Perform actions without user awareness

---

## 12. Canonical Rule

If a behavior is unclear or disputed:
1. Consult `context-pack.md`
2. Consult `decision-log/decisions.md`
3. Consult `engine/scoring-and-scheduling.md`

This PRD defines *what* the system does.  
The engine spec defines *how* it does it.