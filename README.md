# qzWhatNext

Continuously tells you what you should be doing **right now** and **immediately next**—across work, children, health, and home responsibilities—while prioritizing **user trust** through deterministic, explainable behavior.

## What this is (Current Implementation)

qzWhatNext currently provides:

1. **Task management** (in-memory storage)
2. **Automatic stack-ranking** of tasks based on priority tiers
3. **Auto-scheduling** into calendar time slots
4. **Google Calendar sync** (output only)
5. **Overflow detection** and notification

**Note:** This is a work-in-progress MVP. Planned features (Google Sheets import, REST API for task CRUD, SQLite database) are documented in the canonical documents but not yet implemented.

## Product principles (non-negotiable)

- **Trust over optimization**
- **Deterministic rules override AI**
- **User-blocked time is never moved**
- **Manually scheduled events are never moved**
- **Every system action is explainable (one line)**
- **Every system action is reversible**
- **No user data is shared with third parties**

## AI guardrails (critical)

### AI-excluded tasks
A task must be excluded from AI reasoning if either is true:
- The task title starts with a period: `.something`
- The user flags it as AI-excluded

AI-excluded tasks:
- are **never** sent to AI
- **never** receive AI-updated attributes
- **never** auto-change tier due to AI
- may still be scheduled deterministically

### AI is allowed to infer (structured only)
AI may propose (with confidence scores):
- category
- estimated duration
- energy intensity (not used for scheduling in current implementation)
- risk / impact
- dependencies

AI may **not**:
- assign priority tiers
- override hard constraints
- generate free-form user-facing explanations (MVP)

## How prioritization works

- Every task has **exactly one governing priority tier** at any moment.
- Tier assignment follows a **fixed hierarchy** (predictability > personalization).
- AI proposes attributes; the **rules engine assigns tiers deterministically**.
- Tier changes:
  - **High-confidence** attribute corrections can apply automatically (with logging + one-line reason)
  - **Low-confidence** changes require user confirmation

## Scheduling basics

- Default scheduling granularity: **30 minutes**
- Tasks may be **split** across blocks
- The system may move **only** blocks it scheduled itself
- The system may **not** move:
  - user-blocked time
  - manually scheduled events
- When workload exceeds capacity:
  - protect higher-importance tasks
  - defer lower-tier tasks
  - notify the user (no silent failures)

## Current Limitations

**Not yet implemented:**
- Transition Time modeling (deferred to future releases)
- Energy budgeting (deferred to future releases)
- Google Sheets import
- REST API for task CRUD operations
- SQLite database persistence (currently using in-memory storage)
- Smart snooze (manual rescheduling only)

See canonical documents for planned features and future capabilities.

## Canonical documents (source of truth)

If behavior is unclear or disputed, consult in this order:

1. `context-pack.md` (global rules + product identity)
2. `decision-log/decisions.md` (locked decisions)
3. `engine/scoring-and-scheduling.md` (engine spec)
4. `prd/prd.md` (MVP scope + requirements)

**Canonical rule:** Chats generate artifacts. Artifacts replace chats.

## Setup Instructions

### Prerequisites
- Python 3.9 or higher
- Google Cloud project with Calendar API enabled (for calendar sync)

### Installation

1. Create a virtual environment:
```bash
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Set up environment variables (optional, for Google Calendar):
   - Create `.env` file in project root
   - Add Google Calendar credentials path and calendar ID:
     ```
     GOOGLE_CALENDAR_CREDENTIALS_PATH=credentials.json
     GOOGLE_CALENDAR_ID=primary
     ```

4. For Google Calendar integration:
   - Enable Google Calendar API in Google Cloud Console
   - Create OAuth2 credentials (Web app type)
   - Add `http://localhost` to authorized redirect URIs
   - Download OAuth2 credentials as `credentials.json` to project root

5. Run the application:
```bash
uvicorn qzwhatnext.api.app:app --reload
```

The API will be available at `http://localhost:8000`
API documentation at `http://localhost:8000/docs`

**Note:** Tasks are currently stored in-memory and will be lost on server restart. Database persistence is planned but not yet implemented.

## Suggested repo layout

This repo is designed to keep "source of truth" documents close to the code:

