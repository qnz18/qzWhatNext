"""FastAPI web application for qzWhatNext."""

import uuid
from datetime import datetime
from typing import List, Optional, Dict
from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from qzwhatnext.models.task import Task, TaskStatus, TaskCategory, EnergyIntensity
from qzwhatnext.models.scheduled_block import ScheduledBlock
from qzwhatnext.integrations.google_calendar import GoogleCalendarClient
from qzwhatnext.integrations.google_sheets import GoogleSheetsClient
from qzwhatnext.engine.ranking import stack_rank
from qzwhatnext.engine.scheduler import schedule_tasks, SchedulingResult
from qzwhatnext.database.database import get_db, init_db
from qzwhatnext.database.repository import TaskRepository

# Initialize FastAPI app
app = FastAPI(
    title="qzWhatNext API",
    description="Continuously tells you what you should be doing right now and immediately next",
    version="0.1.0"
)

# Add CORS middleware to allow frontend requests
# Must be added before other middleware/routes
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, specify exact origins
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["*"],
)

# Initialize database on startup
@app.on_event("startup")
async def startup_event():
    """Initialize database on application startup."""
    init_db()

# In-memory schedule storage (schedule is not persisted)
schedule_store: Optional[SchedulingResult] = None


# Request/Response models
class TaskCreateRequest(BaseModel):
    """Request model for creating a task."""
    title: str
    notes: Optional[str] = None
    deadline: Optional[datetime] = None
    estimated_duration_min: int = 30
    category: TaskCategory = TaskCategory.UNKNOWN
    source_type: str = "api"
    source_id: Optional[str] = None
    
    @field_validator('category', mode='before')
    @classmethod
    def validate_category(cls, v):
        """Convert invalid categories to UNKNOWN."""
        if v is None:
            return TaskCategory.UNKNOWN
        
        # If it's already a TaskCategory enum, return it
        if isinstance(v, TaskCategory):
            return v
        
        # Try to convert string to enum
        try:
            return TaskCategory(str(v).lower())
        except (ValueError, AttributeError):
            # Invalid category - default to UNKNOWN
            return TaskCategory.UNKNOWN


class TaskUpdateRequest(BaseModel):
    """Request model for updating a task."""
    title: Optional[str] = None
    notes: Optional[str] = None
    status: Optional[TaskStatus] = None
    deadline: Optional[datetime] = None
    estimated_duration_min: Optional[int] = None
    category: Optional[TaskCategory] = None
    energy_intensity: Optional[EnergyIntensity] = None
    risk_score: Optional[float] = None
    impact_score: Optional[float] = None
    ai_excluded: Optional[bool] = None
    
    @field_validator('category', mode='before')
    @classmethod
    def validate_category(cls, v):
        """Convert invalid categories to UNKNOWN if provided."""
        if v is None:
            return None  # Keep None for optional fields
        
        # If it's already a TaskCategory enum, return it
        if isinstance(v, TaskCategory):
            return v
        
        # Try to convert string to enum
        try:
            return TaskCategory(str(v).lower())
        except (ValueError, AttributeError):
            # Invalid category - default to UNKNOWN
            return TaskCategory.UNKNOWN


class TaskResponse(BaseModel):
    """Response model for task."""
    task: Task


class TaskListResponse(BaseModel):
    """Response model for task list."""
    tasks: List[Task]
    count: int


class ImportSheetsRequest(BaseModel):
    """Request model for importing from Google Sheets."""
    spreadsheet_id: str
    range_name: str = "Sheet1!A1:E10"
    has_header: bool = True


class ImportSheetsResponse(BaseModel):
    """Response model for Google Sheets import."""
    imported_count: int
    tasks: List[Task]
    duplicates_detected: int = 0


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
            input, textarea, select { width: 100%; padding: 8px; margin: 5px 0; box-sizing: border-box; }
            label { display: block; margin-top: 10px; font-weight: bold; }
            .form-group { margin: 10px 0; }
        </style>
    </head>
    <body>
        <h1>qzWhatNext</h1>
        <p>Continuously tells you what you should be doing right now and immediately next.</p>
        
        <div class="section">
            <h2>Create Task</h2>
            <form id="createTaskForm" onsubmit="createTask(event)">
                <div class="form-group">
                    <label for="taskTitle">Title *</label>
                    <input type="text" id="taskTitle" required>
                </div>
                <div class="form-group">
                    <label for="taskNotes">Notes</label>
                    <textarea id="taskNotes" rows="3"></textarea>
                </div>
                <div class="form-group">
                    <label for="taskDuration">Duration (minutes)</label>
                    <input type="number" id="taskDuration" value="30" min="1">
                </div>
                <div class="form-group">
                    <label for="taskCategory">Category</label>
                    <select id="taskCategory">
                        <option value="work">Work</option>
                        <option value="child">Child</option>
                        <option value="family">Family</option>
                        <option value="health">Health</option>
                        <option value="personal">Personal</option>
                        <option value="ideas">Ideas</option>
                        <option value="home">Home</option>
                        <option value="admin">Admin</option>
                        <option value="unknown" selected>Unknown</option>
                    </select>
                </div>
                <button type="submit">Create Task</button>
            </form>
        </div>
        
        <div class="section">
            <h2>Import from Google Sheets</h2>
            <form id="importSheetsForm" onsubmit="importFromSheets(event)">
                <div class="form-group">
                    <label for="spreadsheetId">Spreadsheet URL or ID *</label>
                    <input type="text" id="spreadsheetId" required value="https://docs.google.com/spreadsheets/d/1Jf-Ktb_yujoNoUv_aNHCrNM_4xlYU_LPMDlPavuYCuc/edit?usp=sharing" placeholder="Paste full URL from 'Copy link' or just the spreadsheet ID">
                    <small>You can paste the full Google Sheets URL (from "Copy link" button) or just the spreadsheet ID</small>
                </div>
                <div class="form-group">
                    <label for="rangeName">Range</label>
                    <input type="text" id="rangeName" value="Sheet1!A1:E10" placeholder="Sheet1!A1:E10">
                </div>
                <div class="form-group">
                    <label>
                        <input type="checkbox" id="hasHeader" checked> Has header row
                    </label>
                </div>
                <button type="submit">Import Tasks</button>
            </form>
        </div>
        
        <div class="section">
            <h2>Actions</h2>
            <button onclick="buildSchedule()">Build Schedule</button>
            <button onclick="syncCalendar()">Sync to Google Calendar</button>
            <button onclick="viewSchedule()">View Schedule</button>
            <button onclick="viewTasks()">View All Tasks</button>
        </div>
        
        <div class="section">
            <h2>Status</h2>
            <div id="status"></div>
        </div>
        
        <div class="section">
            <h2>Tasks</h2>
            <div id="tasks"></div>
        </div>
        
        <div class="section">
            <h2>Schedule</h2>
            <div id="schedule"></div>
        </div>
        
        <script>
            async function createTask(event) {
                event.preventDefault();
                const status = document.getElementById('status');
                status.innerHTML = 'Creating task...';
                
                const taskData = {
                    title: document.getElementById('taskTitle').value,
                    notes: document.getElementById('taskNotes').value || null,
                    estimated_duration_min: parseInt(document.getElementById('taskDuration').value) || 30,
                    category: document.getElementById('taskCategory').value
                };
                
                try {
                    const response = await fetch('/tasks', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify(taskData)
                    });
                    
                    if (!response.ok) {
                        const error = await response.json();
                        throw new Error(error.detail || 'Failed to create task');
                    }
                    
                    const data = await response.json();
                    status.innerHTML = `Task created: "${data.task.title}"`;
                    document.getElementById('createTaskForm').reset();
                    viewTasks();
                } catch (error) {
                    status.innerHTML = 'Error: ' + error.message;
                }
            }
            
            async function importFromSheets(event) {
                event.preventDefault();
                const status = document.getElementById('status');
                status.innerHTML = 'Importing from Google Sheets...';
                
                const importData = {
                    spreadsheet_id: document.getElementById('spreadsheetId').value,
                    range_name: document.getElementById('rangeName').value || 'Sheet1!A1:E10',
                    has_header: document.getElementById('hasHeader').checked
                };
                
                try {
                    // Use full URL to avoid any origin issues
                    const apiUrl = window.location.origin + '/import/sheets';
                    const response = await fetch(apiUrl, {
                        method: 'POST',
                        headers: { 
                            'Content-Type': 'application/json',
                            'Accept': 'application/json'
                        },
                        body: JSON.stringify(importData),
                        mode: 'cors',
                        credentials: 'same-origin'
                    });
                    
                    if (!response.ok) {
                        const error = await response.json();
                        throw new Error(error.detail || 'Failed to import from Google Sheets');
                    }
                    
                    const data = await response.json();
                    status.innerHTML = `Imported ${data.imported_count} tasks${data.duplicates_detected > 0 ? ` (${data.duplicates_detected} duplicates detected)` : ''}`;
                    document.getElementById('importSheetsForm').reset();
                    viewTasks();
                } catch (error) {
                    console.error('Import error:', error);
                    status.innerHTML = 'Error: ' + error.message + '. Check server console for details.';
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
            
            async function viewTasks() {
                const tasksDiv = document.getElementById('tasks');
                try {
                    const response = await fetch('/tasks');
                    const data = await response.json();
                    
                    if (data.tasks.length === 0) {
                        tasksDiv.innerHTML = '<p>No tasks yet. Create a task or import from Google Sheets.</p>';
                        return;
                    }
                    
                    let html = `<p><strong>Total tasks: ${data.count}</strong></p>`;
                    html += '<table><tr><th>Title</th><th>Category</th><th>Duration</th><th>Status</th></tr>';
                    data.tasks.forEach(task => {
                        html += `<tr>
                            <td>${task.title}</td>
                            <td>${task.category || 'N/A'}</td>
                            <td>${task.estimated_duration_min || 30} min</td>
                            <td>${task.status || 'OPEN'}</td>
                        </tr>`;
                    });
                    html += '</table>';
                    
                    tasksDiv.innerHTML = html;
                } catch (error) {
                    tasksDiv.innerHTML = 'Error: ' + error.message;
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
            
            // Load tasks on page load
            window.onload = function() {
                viewTasks();
            };
        </script>
    </body>
    </html>
    """


@app.get("/health")
async def health():
    """Health check endpoint."""
    return {"status": "healthy", "version": "0.1.0"}


@app.get("/favicon.ico")
async def favicon():
    """Handle favicon requests to prevent 404 errors."""
    return Response(status_code=204)  # No Content


# Task CRUD endpoints
@app.post("/tasks", response_model=TaskResponse, status_code=201)
async def create_task(request: TaskCreateRequest, db: Session = Depends(get_db)):
    """Create a new task."""
    repo = TaskRepository(db)
    
    # Check for duplicates if source_id is provided
    if request.source_id:
        duplicates = repo.find_duplicates(request.source_type, request.source_id, request.title)
        if duplicates:
            # For MVP, we just log but still create (no auto-dedupe)
            pass  # TODO: Add logging for duplicate detection
    
    # Create task from request
    now = datetime.utcnow()
    task = Task(
        id=str(uuid.uuid4()),
        source_type=request.source_type,
        source_id=request.source_id,
        title=request.title,
        notes=request.notes,
        status=TaskStatus.OPEN,
        created_at=now,
        updated_at=now,
        deadline=request.deadline,
        estimated_duration_min=request.estimated_duration_min,
        duration_confidence=0.5,
        category=request.category,
        energy_intensity=EnergyIntensity.MEDIUM,
        risk_score=0.3,
        impact_score=0.3,
        dependencies=[],
        flexibility_window=None,
        ai_excluded=request.title.startswith('.') if request.title else False,
        manual_priority_locked=False,
        user_locked=False,
        manually_scheduled=False,
    )
    
    try:
        created_task = repo.create(task)
        return TaskResponse(task=created_task)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create task: {str(e)}")


@app.get("/tasks", response_model=TaskListResponse)
async def list_tasks(db: Session = Depends(get_db)):
    """List all tasks."""
    repo = TaskRepository(db)
    try:
        tasks = repo.get_all()
        return TaskListResponse(tasks=tasks, count=len(tasks))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to list tasks: {str(e)}")


@app.get("/tasks/{task_id}", response_model=TaskResponse)
async def get_task(task_id: str, db: Session = Depends(get_db)):
    """Get a task by ID."""
    repo = TaskRepository(db)
    task = repo.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")
    return TaskResponse(task=task)


@app.put("/tasks/{task_id}", response_model=TaskResponse)
async def update_task(task_id: str, request: TaskUpdateRequest, db: Session = Depends(get_db)):
    """Update a task."""
    repo = TaskRepository(db)
    task = repo.get(task_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")
    
    # Update fields from request (only provided fields)
    if request.title is not None:
        task.title = request.title
    if request.notes is not None:
        task.notes = request.notes
    if request.status is not None:
        task.status = request.status
    if request.deadline is not None:
        task.deadline = request.deadline
    if request.estimated_duration_min is not None:
        task.estimated_duration_min = request.estimated_duration_min
    if request.category is not None:
        task.category = request.category
    if request.energy_intensity is not None:
        task.energy_intensity = request.energy_intensity
    if request.risk_score is not None:
        task.risk_score = request.risk_score
    if request.impact_score is not None:
        task.impact_score = request.impact_score
    if request.ai_excluded is not None:
        task.ai_excluded = request.ai_excluded
    
    task.updated_at = datetime.utcnow()
    
    try:
        updated_task = repo.update(task)
        return TaskResponse(task=updated_task)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to update task: {str(e)}")


@app.delete("/tasks/{task_id}", status_code=204)
async def delete_task(task_id: str, db: Session = Depends(get_db)):
    """Delete a task."""
    repo = TaskRepository(db)
    success = repo.delete(task_id)
    if not success:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")
    return None


# Google Sheets import endpoint
@app.post("/import/sheets", response_model=ImportSheetsResponse)
async def import_from_sheets(request: ImportSheetsRequest, db: Session = Depends(get_db)):
    """Import tasks from Google Sheets.
    
    Note: On first use, this will open a browser window for OAuth authentication.
    The request will wait for you to complete the OAuth flow in the browser.
    """
    repo = TaskRepository(db)
    
    try:
        # Import tasks from Google Sheets
        # Note: Authentication happens in GoogleSheetsClient.__init__ which may open a browser
        # for OAuth flow on first use. This is a blocking operation that waits for OAuth completion.
        # Check the server console/terminal for authentication status messages.
        sheets_client = GoogleSheetsClient()
        imported_tasks = sheets_client.import_tasks(
            spreadsheet_id=request.spreadsheet_id,
            range_name=request.range_name,
            has_header=request.has_header
        )
        
        # Save tasks to database and detect duplicates
        saved_tasks = []
        duplicates_count = 0
        
        for task in imported_tasks:
            # Check for duplicates
            duplicates = repo.find_duplicates(task.source_type, task.source_id, task.title)
            if duplicates:
                duplicates_count += 1
                # For MVP: notify user but still import (no auto-dedupe)
            
            # Create task in database
            try:
                created_task = repo.create(task)
                saved_tasks.append(created_task)
            except Exception as e:
                # Log error but continue with other tasks
                print(f"Error saving task {task.title}: {e}")
                continue
        
        return ImportSheetsResponse(
            imported_count=len(saved_tasks),
            tasks=saved_tasks,
            duplicates_detected=duplicates_count
        )
        
    except FileNotFoundError as e:
        raise HTTPException(
            status_code=400,
            detail=f"Google Sheets credentials not found. {str(e)}"
        )
    except ValueError as e:
        # Spreadsheet ID extraction error
        raise HTTPException(
            status_code=400,
            detail=str(e)
        )
    except Exception as e:
        error_msg = str(e)
        # Check if it's an authentication issue
        if "credentials" in error_msg.lower() or "authentication" in error_msg.lower():
            raise HTTPException(
                status_code=401,
                detail=f"Authentication failed: {error_msg}"
            )
        raise HTTPException(
            status_code=500,
            detail=f"Failed to import from Google Sheets: {error_msg}"
        )


@app.post("/schedule", response_model=ScheduleResponse)
async def build_schedule(db: Session = Depends(get_db)):
    """Build schedule from tasks in database."""
    global schedule_store
    
    repo = TaskRepository(db)
    tasks = repo.get_open()
    
    if not tasks:
        raise HTTPException(status_code=400, detail="No tasks available. Create tasks first.")
    
    try:
        # Stack rank tasks
        ranked_tasks = stack_rank(tasks)
        
        # Schedule tasks
        schedule_result = schedule_tasks(ranked_tasks)
        
        # Store schedule (in-memory for now)
        schedule_store = schedule_result
        
        # Build task titles map for frontend lookup
        task_dict = {task.id: task for task in tasks}
        task_titles = {}
        for block in schedule_result.scheduled_blocks:
            if block.entity_type == "task" and block.entity_id in task_dict:
                task_titles[block.entity_id] = task_dict[block.entity_id].title
        
        return ScheduleResponse(
            scheduled_blocks=schedule_result.scheduled_blocks,
            overflow_tasks=schedule_result.overflow_tasks,
            start_time=schedule_result.start_time,
            task_titles=task_titles
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to build schedule: {str(e)}")


@app.get("/schedule", response_model=ScheduleResponse)
async def view_schedule(db: Session = Depends(get_db)):
    """View current schedule."""
    if schedule_store is None:
        raise HTTPException(status_code=404, detail="No schedule available. Build a schedule first.")
    
    # Build task titles map for frontend lookup
    repo = TaskRepository(db)
    tasks = repo.get_all()
    task_dict = {task.id: task for task in tasks}
    task_titles = {}
    for block in schedule_store.scheduled_blocks:
        if block.entity_type == "task" and block.entity_id in task_dict:
            task_titles[block.entity_id] = task_dict[block.entity_id].title
    
    return ScheduleResponse(
        scheduled_blocks=schedule_store.scheduled_blocks,
        overflow_tasks=schedule_store.overflow_tasks,
        start_time=schedule_store.start_time,
        task_titles=task_titles
    )


@app.post("/sync-calendar", response_model=SyncResponse)
async def sync_calendar(db: Session = Depends(get_db)):
    """Sync schedule to Google Calendar."""
    global schedule_store
    
    if schedule_store is None:
        raise HTTPException(status_code=400, detail="No schedule available. Build a schedule first.")
    
    try:
        # Create Google Calendar client
        calendar_client = GoogleCalendarClient()
        
        # Get tasks from database
        repo = TaskRepository(db)
        tasks = repo.get_all()
        tasks_dict = {task.id: task for task in tasks}
        
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
