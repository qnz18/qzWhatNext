# Testing Guide for qzWhatNext

This guide covers testing the minimal MVP implementation.

## Prerequisites

1. Python 3.9+ installed
2. Virtual environment created and activated
3. Dependencies installed: `pip install -r requirements.txt`
4. `.env` file configured (optional, for Google Calendar sync):
   - `GOOGLE_OAUTH_CLIENT_ID`
   - `GOOGLE_OAUTH_CLIENT_SECRET`
   - `JWT_SECRET_KEY`
   - `TOKEN_ENCRYPTION_KEY`
   - `GOOGLE_CALENDAR_ID` (optional; defaults to "primary")

## Local Testing

### 1. Start the Application

```bash
uvicorn qzwhatnext.api.app:app --reload
```

The application will be available at `http://localhost:8000`

### 2. Test via Web UI

1. Open `http://localhost:8000` in your browser
2. Use the API docs at `/docs` to test endpoints
3. Create tasks via `POST /tasks`
4. Build schedule via `POST /schedule`
5. View schedule via `GET /schedule`
6. Sync to Google Calendar via `POST /sync-calendar` (first time will prompt you to connect via OAuth)

### 3. Test via API

#### Health Check
```bash
curl http://localhost:8000/health
```

#### Create Task
```bash
curl -X POST http://localhost:8000/tasks \
  -H "Content-Type: application/json" \
  -d '{"title": "Test Task", "category": "unknown"}'
```

#### List Tasks
```bash
curl http://localhost:8000/tasks
```

#### Get Specific Task
```bash
curl http://localhost:8000/tasks/{task_id}
```

#### Update Task
```bash
curl -X PUT http://localhost:8000/tasks/{task_id} \
  -H "Content-Type: application/json" \
  -d '{"title": "Updated Task Title"}'
```

#### Delete Task
```bash
curl -X DELETE http://localhost:8000/tasks/{task_id}
```

#### Import from Google Sheets
```bash
curl -X POST http://localhost:8000/import/sheets \
  -H "Content-Type: application/json" \
  -d '{"spreadsheet_id": "YOUR_SHEET_ID", "range_name": "Sheet1!A2:Z1000"}'
```

#### Build Schedule
```bash
curl -X POST http://localhost:8000/schedule
```

#### View Schedule
```bash
curl http://localhost:8000/schedule
```

#### Sync to Calendar
```bash
curl -X POST http://localhost:8000/sync-calendar
```

### 4. Test via FastAPI Docs

Visit `http://localhost:8000/docs` for interactive API documentation.

## Testing Determinism

To verify deterministic behavior:

1. Import the same set of tasks twice
2. Build schedules for both
3. Compare the schedules - they should be identical

```python
# Example test script
from qzwhatnext.database.database import init_db, SessionLocal
from qzwhatnext.database.repository import TaskRepository
from qzwhatnext.engine.ranking import stack_rank
from qzwhatnext.engine.scheduler import schedule_tasks
from qzwhatnext.models.task import Task, TaskStatus, TaskCategory
from datetime import datetime
import uuid

# Initialize database
init_db()

# Create test tasks via repository
db = SessionLocal()
repo = TaskRepository(db)

task1 = Task(
    id=str(uuid.uuid4()),
    source_type='api',
    source_id=None,
    title='Test Task 1',
    status=TaskStatus.OPEN,
    created_at=datetime.utcnow(),
    updated_at=datetime.utcnow(),
    category=TaskCategory.UNKNOWN
)
task2 = Task(
    id=str(uuid.uuid4()),
    source_type='api',
    source_id=None,
    title='Test Task 2',
    status=TaskStatus.OPEN,
    created_at=datetime.utcnow(),
    updated_at=datetime.utcnow(),
    category=TaskCategory.UNKNOWN
)

created1 = repo.create(task1)
created2 = repo.create(task2)

# Get tasks from database
tasks = repo.get_all()

# Build schedules
ranked = stack_rank(tasks)
schedule = schedule_tasks(ranked)

# Verify schedule was created
assert len(schedule.scheduled_blocks) > 0

# Cleanup
repo.delete(created1.id)
repo.delete(created2.id)
db.close()
```

## Testing AI Exclusion

1. Create a task via API with title starting with `.` (e.g., `.Private task`):
   ```bash
   curl -X POST http://localhost:8000/tasks \
     -H "Content-Type: application/json" \
     -d '{"title": ".Private task", "category": "unknown"}'
   ```
2. Verify the task has `ai_excluded=True` (check response or get task)
3. Verify the task is still scheduled (AI exclusion doesn't prevent scheduling)

## Testing Tier Assignment

Test that tasks are assigned to correct tiers:

- Task with deadline < 24h → Tier 1
- Task with category "child" → Tier 4
- Task with category "health" → Tier 5
- Task with category "work" → Tier 6
- Default → Tier 9

## Testing Overflow Detection

1. Add many tasks via API (more than can fit in available time):
   ```bash
   for i in {1..50}; do
     curl -X POST http://localhost:8000/tasks \
       -H "Content-Type: application/json" \
       -d "{\"title\": \"Task $i\", \"category\": \"unknown\", \"estimated_duration_min\": 60}"
   done
   ```
2. Build schedule: `curl -X POST http://localhost:8000/schedule`
3. Verify overflow tasks are identified in the response

## Common Issues

### Task Storage
- Tasks are stored in SQLite database (`qzwhatnext.db`)
- Database is automatically created on first run
- Tasks persist across server restarts
- If database errors occur, check file permissions in project directory

### Google Calendar/Sheets OAuth2 Errors
- For Google Calendar sync: ensure OAuth client redirect URI includes `/auth/google/calendar/callback` and required env vars are set
- For Google Sheets import (legacy/local-dev flow): ensure `credentials.json` exists and is valid
- Ensure Calendar API and Sheets API are enabled in Google Cloud Console
- Verify OAuth2 consent screen is configured

### Import/Schedule Errors
- For Google Sheets import: Verify spreadsheet ID is correct and sheet is accessible
- Check that tasks were imported successfully (verify via `GET /tasks`)
- Verify task data is valid (no missing required fields)
- Review application logs for errors

## Next Steps

After minimal MVP is working:
- Add unit tests for each module
- Add integration tests for end-to-end flow
- Add tests for edge cases (empty tasks, invalid data, etc.)
- Add performance tests for large task sets

