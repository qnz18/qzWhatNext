"""FastAPI web application for qzWhatNext."""

from datetime import datetime
from typing import List, Optional, Dict
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from qzwhatnext.models.task import Task
from qzwhatnext.models.scheduled_block import ScheduledBlock
from qzwhatnext.integrations.todoist import TodoistClient
from qzwhatnext.integrations.google_calendar import GoogleCalendarClient
from qzwhatnext.engine.ranking import stack_rank
from qzwhatnext.engine.scheduler import schedule_tasks, SchedulingResult

# Initialize FastAPI app
app = FastAPI(
    title="qzWhatNext API",
    description="Continuously tells you what you should be doing right now and immediately next",
    version="0.1.0"
)

# In-memory storage for MVP
tasks_store: Dict[str, Task] = {}
schedule_store: Optional[SchedulingResult] = None


# Response models
class ImportResponse(BaseModel):
    """Response for task import."""
    imported_count: int
    tasks: List[Task]


class ScheduleResponse(BaseModel):
    """Response for schedule view."""
    scheduled_blocks: List[ScheduledBlock]
    overflow_tasks: List[Task]
    start_time: Optional[datetime]
    task_titles: Dict[str, str] = Field(default_factory=dict, description="Map of entity_id to task title")


class SyncResponse(BaseModel):
    """Response for calendar sync."""
    events_created: int
    event_ids: List[str]


@app.get("/", response_class=HTMLResponse)
async def root():
    """Root endpoint with basic UI."""
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>qzWhatNext</title>
        <style>
            body { font-family: Arial, sans-serif; max-width: 800px; margin: 50px auto; padding: 20px; }
            button { padding: 10px 20px; margin: 5px; cursor: pointer; }
            .section { margin: 20px 0; padding: 15px; border: 1px solid #ddd; border-radius: 5px; }
            table { width: 100%; border-collapse: collapse; margin-top: 10px; }
            th, td { padding: 8px; text-align: left; border-bottom: 1px solid #ddd; }
            th { background-color: #f2f2f2; }
        </style>
    </head>
    <body>
        <h1>qzWhatNext</h1>
        <p>Continuously tells you what you should be doing right now and immediately next.</p>
        
        <div class="section">
            <h2>Actions</h2>
            <button onclick="importTasks()">Import from Todoist</button>
            <button onclick="buildSchedule()">Build Schedule</button>
            <button onclick="syncCalendar()">Sync to Google Calendar</button>
            <button onclick="viewSchedule()">View Schedule</button>
        </div>
        
        <div class="section">
            <h2>Status</h2>
            <div id="status"></div>
        </div>
        
        <div class="section">
            <h2>Schedule</h2>
            <div id="schedule"></div>
        </div>
        
        <script>
            async function importTasks() {
                const status = document.getElementById('status');
                status.innerHTML = 'Importing tasks...';
                try {
                    const response = await fetch('/import', { method: 'POST' });
                    if (!response.ok) {
                        const errorData = await response.json();
                        status.innerHTML = 'Error: ' + (errorData.detail || response.statusText);
                        return;
                    }
                    const data = await response.json();
                    if (data.imported_count !== undefined) {
                        status.innerHTML = `Imported ${data.imported_count} tasks`;
                    } else {
                        status.innerHTML = 'Error: Invalid response from server';
                    }
                } catch (error) {
                    status.innerHTML = 'Error: ' + error.message;
                }
            }
            
            async function buildSchedule() {
                const status = document.getElementById('status');
                status.innerHTML = 'Building schedule...';
                try {
                    const response = await fetch('/schedule', { method: 'POST' });
                    const data = await response.json();
                    status.innerHTML = `Schedule built: ${data.scheduled_blocks.length} blocks, ${data.overflow_tasks.length} overflow`;
                    viewSchedule();
                } catch (error) {
                    status.innerHTML = 'Error: ' + error.message;
                }
            }
            
            async function syncCalendar() {
                const status = document.getElementById('status');
                status.innerHTML = 'Syncing to Google Calendar...';
                try {
                    const response = await fetch('/sync-calendar', { method: 'POST' });
                    const data = await response.json();
                    status.innerHTML = `Synced ${data.events_created} events to Google Calendar`;
                } catch (error) {
                    status.innerHTML = 'Error: ' + error.message;
                }
            }
            
            async function viewSchedule() {
                const scheduleDiv = document.getElementById('schedule');
                try {
                    const response = await fetch('/schedule');
                    const data = await response.json();
                    
                    if (data.scheduled_blocks.length === 0) {
                        scheduleDiv.innerHTML = '<p>No schedule available. Build a schedule first.</p>';
                        return;
                    }
                    
                    let html = '<table><tr><th>Start</th><th>End</th><th>Task</th></tr>';
                    data.scheduled_blocks.forEach(block => {
                        let taskName = 'Unknown';
                        if (block.entity_type === 'task' && data.task_titles && data.task_titles[block.entity_id]) {
                            taskName = data.task_titles[block.entity_id];
                        } else if (block.entity_type === 'transition') {
                            taskName = 'Transition';
                        } else {
                            taskName = block.entity_id; // Fallback to ID if title not found
                        }
                        html += `<tr>
                            <td>${new Date(block.start_time).toLocaleString()}</td>
                            <td>${new Date(block.end_time).toLocaleString()}</td>
                            <td>${taskName}</td>
                        </tr>`;
                    });
                    html += '</table>';
                    
                    if (data.overflow_tasks.length > 0) {
                        html += `<p><strong>Overflow tasks (${data.overflow_tasks.length}):</strong></p><ul>`;
                        data.overflow_tasks.forEach(task => {
                            html += `<li>${task.title}</li>`;
                        });
                        html += '</ul>';
                    }
                    
                    scheduleDiv.innerHTML = html;
                } catch (error) {
                    scheduleDiv.innerHTML = 'Error: ' + error.message;
                }
            }
        </script>
    </body>
    </html>
    """


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "healthy", "version": "0.1.0"}


@app.post("/import", response_model=ImportResponse)
async def import_tasks():
    """Import tasks from Todoist."""
    try:
        client = TodoistClient()
        tasks = client.import_tasks()
        
        # Store tasks in memory
        for task in tasks:
            tasks_store[task.id] = task
        
        return ImportResponse(
            imported_count=len(tasks),
            tasks=list(tasks_store.values())
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to import tasks: {str(e)}")


@app.post("/schedule", response_model=ScheduleResponse)
async def build_schedule():
    """Build schedule from imported tasks."""
    global schedule_store
    
    if not tasks_store:
        raise HTTPException(status_code=400, detail="No tasks available. Import tasks first.")
    
    try:
        # Get all tasks
        tasks = list(tasks_store.values())
        
        # Stack rank tasks
        ranked_tasks = stack_rank(tasks)
        
        # Schedule tasks
        schedule_result = schedule_tasks(ranked_tasks)
        
        # Store schedule
        schedule_store = schedule_result
        
        # Build task titles map for frontend lookup
        task_titles = {}
        for block in schedule_result.scheduled_blocks:
            if block.entity_type == "task" and block.entity_id in tasks_store:
                task_titles[block.entity_id] = tasks_store[block.entity_id].title
        
        return ScheduleResponse(
            scheduled_blocks=schedule_result.scheduled_blocks,
            overflow_tasks=schedule_result.overflow_tasks,
            start_time=schedule_result.start_time,
            task_titles=task_titles
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to build schedule: {str(e)}")


@app.get("/schedule", response_model=ScheduleResponse)
async def view_schedule():
    """View current schedule."""
    if schedule_store is None:
        raise HTTPException(status_code=404, detail="No schedule available. Build a schedule first.")
    
    # Build task titles map for frontend lookup
    task_titles = {}
    for block in schedule_store.scheduled_blocks:
        if block.entity_type == "task" and block.entity_id in tasks_store:
            task_titles[block.entity_id] = tasks_store[block.entity_id].title
    
    return ScheduleResponse(
        scheduled_blocks=schedule_store.scheduled_blocks,
        overflow_tasks=schedule_store.overflow_tasks,
        start_time=schedule_store.start_time,
        task_titles=task_titles
    )


@app.post("/sync-calendar", response_model=SyncResponse)
async def sync_calendar():
    """Sync schedule to Google Calendar."""
    global schedule_store
    
    if schedule_store is None:
        raise HTTPException(status_code=400, detail="No schedule available. Build a schedule first.")
    
    try:
        # Create Google Calendar client
        calendar_client = GoogleCalendarClient()
        
        # Create tasks dictionary for metadata
        tasks_dict = {task.id: task for task in tasks_store.values()}
        
        # Create events from scheduled blocks
        events = calendar_client.create_events_from_blocks(
            schedule_store.scheduled_blocks,
            tasks_dict
        )
        
        return SyncResponse(
            events_created=len(events),
            event_ids=[event['id'] for event in events]
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to sync calendar: {str(e)}")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

