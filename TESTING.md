# Testing Guide for qzWhatNext

This guide covers testing the minimal MVP implementation.

## Prerequisites

1. Python 3.9+ installed
2. Virtual environment created and activated
3. Dependencies installed: `pip install -r requirements.txt`
4. `.env` file configured (optional, for Google Calendar):
   - `GOOGLE_CALENDAR_CREDENTIALS_PATH` (path to credentials.json)
   - `GOOGLE_CALENDAR_ID` (defaults to "primary")

## Local Testing

### 1. Start the Application

```bash
uvicorn qzwhatnext.api.app:app --reload
```

The application will be available at `http://localhost:8000`

### 2. Test via Web UI

**Note:** Task creation UI is not yet implemented. Tasks must be added programmatically via API.

1. Open `http://localhost:8000` in your browser
2. Add tasks via API (see API docs at `/docs`)
3. Click "Build Schedule" to create a schedule
4. Click "View Schedule" to see the scheduled blocks
5. Click "Sync to Google Calendar" to write events (requires OAuth2 setup)

### 3. Test via API

#### Health Check
```bash
curl http://localhost:8000/health
```

#### Create Task (via API)
**Note:** Task CRUD endpoints are not yet implemented. Tasks must be added programmatically.

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
from qzwhatnext.engine.ranking import stack_rank
from qzwhatnext.engine.scheduler import schedule_tasks
from qzwhatnext.models.task import Task, TaskStatus, TaskCategory
from datetime import datetime

# Create test tasks (programmatically - no import yet)
tasks1 = [Task(...), Task(...)]  # Create tasks with same data
tasks2 = [Task(...), Task(...)]  # Create tasks with same data

# Build schedules
ranked1 = stack_rank(tasks1)
ranked2 = stack_rank(tasks2)

schedule1 = schedule_tasks(ranked1)
schedule2 = schedule_tasks(ranked2)

# Compare (should be identical)
assert len(schedule1.scheduled_blocks) == len(schedule2.scheduled_blocks)
```

## Testing AI Exclusion

1. Create a task in Todoist with title starting with `.` (e.g., `.Private task`)
2. Import tasks
3. Verify the task has `ai_excluded=True`
4. Verify the task is still scheduled (AI exclusion doesn't prevent scheduling)

## Testing Tier Assignment

Test that tasks are assigned to correct tiers:

- Task with deadline < 24h → Tier 1
- Task with category "child" → Tier 4
- Task with category "health" → Tier 5
- Task with category "work" → Tier 6
- Default → Tier 9

## Testing Overflow Detection

1. Add many tasks programmatically (more than can fit in available time)
2. Build schedule
3. Verify overflow tasks are identified in the response

## Common Issues

### Task Storage
- Tasks are stored in-memory and will be lost on server restart
- Database persistence is planned but not yet implemented
- Check API token is valid and not expired
- Verify network connectivity

### Google Calendar OAuth2 Errors
- Ensure `credentials.json` exists and is valid
- First run will open browser for authorization
- Token will be saved to `token.json`
- Ensure Calendar API is enabled in Google Cloud Console

### Import/Schedule Errors
- Check that tasks were imported successfully
- Verify task data is valid (no missing required fields)
- Review application logs for errors

## Next Steps

After minimal MVP is working:
- Add unit tests for each module
- Add integration tests for end-to-end flow
- Add tests for edge cases (empty tasks, invalid data, etc.)
- Add performance tests for large task sets

