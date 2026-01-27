"""FastAPI web application for qzWhatNext."""

import logging
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Dict
from urllib.parse import urlencode, urlparse, urlunparse

import jwt
import requests
from fastapi import FastAPI, HTTPException, Depends, Request, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, Response, RedirectResponse
from google.auth.transport.requests import Request as GoogleAuthRequest
from google.oauth2.credentials import Credentials as GoogleCredentials
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import text
from sqlalchemy.orm import Session

from qzwhatnext.models.task import Task, TaskStatus, TaskCategory, EnergyIntensity
from qzwhatnext.models.scheduled_block import ScheduledBlock
from qzwhatnext.models.task_factory import create_task_base, determine_ai_exclusion
from qzwhatnext.api.auth_models import GoogleOAuthCallbackRequest, AuthResponse
from qzwhatnext.integrations.google_calendar import (
    GoogleCalendarClient,
    PRIVATE_KEY_BLOCK_ID,
    PRIVATE_KEY_MANAGED,
    PRIVATE_KEY_TASK_ID,
)
from qzwhatnext.integrations.google_sheets import GoogleSheetsClient
from qzwhatnext.engine.ranking import stack_rank
from qzwhatnext.engine.scheduler import schedule_tasks, SchedulingResult
from qzwhatnext.engine.inference import infer_category, generate_title, estimate_duration
from qzwhatnext.database.database import get_db, init_db
from qzwhatnext.database.repository import TaskRepository
from qzwhatnext.database.google_oauth_token_repository import (
    GoogleOAuthTokenRepository,
    decrypt_secret,
)
from qzwhatnext.database.user_repository import UserRepository
from qzwhatnext.database.scheduled_block_repository import ScheduledBlockRepository
from qzwhatnext.database.models import ApiTokenDB
from qzwhatnext.auth.jwt import create_access_token
from qzwhatnext.auth.google_oauth import verify_google_token
from qzwhatnext.auth.dependencies import get_current_user
from qzwhatnext.auth.shortcut_tokens import generate_shortcut_token, hash_shortcut_token
from qzwhatnext.models.user import User

# Initialize logger
logger = logging.getLogger(__name__)


# Helper functions
def _build_task_titles_dict(tasks: List[Task], scheduled_blocks: List[ScheduledBlock]) -> Dict[str, str]:
    """Build a dictionary mapping task IDs to task titles for scheduled blocks.
    
    Args:
        tasks: List of tasks
        scheduled_blocks: List of scheduled blocks to extract task IDs from
        
    Returns:
        Dictionary mapping entity_id to task title for task-type blocks
    """
    task_dict = {task.id: task for task in tasks}
    task_titles = {}
    for block in scheduled_blocks:
        if block.entity_type == "task" and block.entity_id in task_dict:
            task_titles[block.entity_id] = task_dict[block.entity_id].title
    return task_titles


def _public_url_for(request: Request, endpoint_name: str) -> str:
    """Create an absolute URL honoring reverse-proxy scheme headers (Cloud Run)."""
    url = str(request.url_for(endpoint_name))
    forwarded_proto = request.headers.get("x-forwarded-proto")
    if forwarded_proto:
        parsed = urlparse(url)
        url = urlunparse(parsed._replace(scheme=forwarded_proto))
    return url


def _encode_calendar_oauth_state(user_id: str) -> str:
    """Signed state token binding OAuth callback to a user (short-lived)."""
    secret = os.getenv("JWT_SECRET_KEY", "change-me-in-production")
    payload = {
        "sub": user_id,
        "purpose": "google_calendar_oauth",
        "jti": str(uuid.uuid4()),
        "exp": datetime.utcnow() + timedelta(minutes=10),
        "iat": datetime.utcnow(),
    }
    return jwt.encode(payload, secret, algorithm=os.getenv("JWT_ALGORITHM", "HS256"))


def _decode_calendar_oauth_state(state: str) -> str:
    secret = os.getenv("JWT_SECRET_KEY", "change-me-in-production")
    try:
        payload = jwt.decode(
            state,
            secret,
            algorithms=[os.getenv("JWT_ALGORITHM", "HS256")],
            options={"require": ["exp", "sub"]},
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail="Invalid OAuth state") from e
    if payload.get("purpose") != "google_calendar_oauth":
        raise HTTPException(status_code=400, detail="Invalid OAuth state")
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=400, detail="Invalid OAuth state")
    return str(user_id)


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
    """Initialize database and logging on application startup."""
    # Configure logging format if not already configured
    if not logging.root.handlers:
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
    init_db()

# Note: Schedule is now persisted in database via ScheduledBlockRepository


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


class TaskAddSmartRequest(BaseModel):
    """Request model for iOS Shortcut task creation (notes only, auto-generates timestamp title)."""
    notes: str


class TaskResponse(BaseModel):
    """Response model for task."""
    task: Task


class TaskListResponse(BaseModel):
    """Response model for task list."""
    tasks: List[Task]
    count: int


class BulkTaskIdsRequest(BaseModel):
    """Request model for bulk task actions based on explicit IDs."""
    task_ids: List[str] = Field(..., min_length=1, description="List of task IDs to operate on")


class BulkActionResponse(BaseModel):
    """Response model for bulk delete/restore/purge actions."""
    affected_count: int
    not_found_ids: List[str] = Field(default_factory=list)


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


class ScheduledBlockResponse(BaseModel):
    """Response model for scheduled block operations."""
    block: ScheduledBlock


class ShortcutTokenStatusResponse(BaseModel):
    """Response for shortcut token status."""
    active: bool
    token_prefix: Optional[str] = None
    created_at: Optional[datetime] = None
    last_used_at: Optional[datetime] = None


class ShortcutTokenCreateResponse(BaseModel):
    """Response for creating a new shortcut token (token returned once)."""
    token: str
    token_prefix: str
    created_at: datetime


@app.get("/", response_class=HTMLResponse)
async def root():
    """Root endpoint with basic UI."""
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>qzWhatNext</title>
        <script src="https://accounts.google.com/gsi/client" async defer></script>
        <style>
            body { font-family: Arial, sans-serif; max-width: 800px; margin: 50px auto; padding: 20px; }
            button { padding: 10px 20px; margin: 5px; cursor: pointer; }
            .section { margin: 20px 0; padding: 15px; border: 1px solid #ddd; border-radius: 5px; }
            table { width: 100%; border-collapse: collapse; }
            th, td { padding: 8px; text-align: left; border-bottom: 1px solid #ddd; }
            th { background-color: #f2f2f2; position: sticky; top: 0; z-index: 10; }
            td.notes { max-width: 300px; word-wrap: break-word; white-space: normal; }
            .tasks-container { max-height: 500px; overflow-y: auto; border: 1px solid #ddd; border-radius: 5px; margin-top: 10px; }
            input, textarea, select { width: 100%; padding: 8px; margin: 5px 0; box-sizing: border-box; }
            label { display: block; margin-top: 10px; font-weight: bold; }
            .form-group { margin: 10px 0; }
            .muted { color: #666; font-size: 0.9em; }
            .row { display: flex; gap: 12px; align-items: center; flex-wrap: wrap; }
            .row.grow { align-items: flex-start; }
            .row .spacer { flex: 1 1 auto; }
            .row .wrap { flex: 1 1 260px; min-width: 220px; }
            .task-select { width: auto; margin: 0; }
            th.select-col, td.select-col { width: 44px; text-align: center; }
            #tasksUpdated { display: inline-block; }
            .tasks-actions { display: block; margin-top: 6px; }
            .tasks-actions label { white-space: nowrap; display: inline-flex; align-items: center; gap: 6px; font-weight: normal; margin-top: 0; }
            .tasks-actions-bottom { margin-top: 10px; display: flex; gap: 10px; justify-content: flex-start; flex-wrap: wrap; }
            .tasks-actions-bottom button { width: auto; padding: 6px 12px; font-size: 0.9em; }
        </style>
    </head>
    <body>
        <h1>qzWhatNext</h1>
        <p>Continuously tells you what you should be doing right now and immediately next.</p>

        <div class="section">
            <h2>Sign in</h2>
            <div class="row">
                <div id="gsi-button"></div>
                <button onclick="signOut()">Sign out</button>
            </div>
            <div id="authStatus" class="muted"></div>
            <div id="userInfo" class="muted"></div>
            <div class="row" style="margin-top: 10px;">
                <button id="copyJwtBtn" onclick="copyJwt()" disabled>Copy JWT</button>
                <span id="jwtStatus" class="muted"></span>
            </div>
        </div>

        <div class="section">
            <h2>Tasks</h2>
            <div class="row">
                <button onclick="viewTasks()">Refresh Tasks</button>
                <span id="tasksUpdated" class="muted wrap"></span>
            </div>
            <div class="tasks-actions">
                <label>
                    <input type="checkbox" id="selectAllTasks" onchange="toggleSelectAllTasks(this.checked)">
                    Select all
                </label>
            </div>
            <div id="tasks"></div>
        </div>

        <div class="section">
            <h2>Actions</h2>
            <button onclick="buildSchedule()">Build Schedule</button>
            <button onclick="syncCalendar()">Sync to Google Calendar</button>
            <button onclick="viewSchedule()">View Schedule</button>
            <button onclick="viewTasks()">View All Tasks</button>
        </div>
        
        <div class="section">
            <h2>Schedule</h2>
            <div id="schedule"></div>
        </div>
        
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
            <h2>iOS Shortcut Token</h2>
            <p class="muted">Generate a long-lived token for iOS Shortcuts. Keep it secret. You can revoke it anytime.</p>
            <div class="row">
                <button onclick="createShortcutToken()">Create / Rotate Token</button>
                <button onclick="revokeShortcutToken()">Revoke Token</button>
                <button onclick="loadShortcutTokenStatus()">Refresh Status</button>
            </div>
            <div id="shortcutTokenStatus" class="muted"></div>
            <pre id="shortcutTokenValue" style="white-space: pre-wrap;"></pre>
        </div>

        <div class="section">
            <h2>Status</h2>
            <div id="status"></div>
        </div>
        
        <script>
            const ACCESS_TOKEN_KEY = "qz_access_token";
            let authVersion = 0;
            let currentUserEmail = null;
            const activeRequestControllers = new Set();

            function isStale(version) {
                return version !== authVersion;
            }

            function bumpAuthVersion() {
                authVersion += 1;
                for (const controller of activeRequestControllers) {
                    try { controller.abort(); } catch (e) { /* ignore */ }
                }
                activeRequestControllers.clear();
            }

            function beginRequest(version) {
                const controller = new AbortController();
                activeRequestControllers.add(controller);
                return {
                    signal: controller.signal,
                    done: () => activeRequestControllers.delete(controller),
                    version: version
                };
            }

            function getAccessToken() {
                return localStorage.getItem(ACCESS_TOKEN_KEY);
            }

            function setAccessToken(token) {
                if (token) {
                    localStorage.setItem(ACCESS_TOKEN_KEY, token);
                } else {
                    localStorage.removeItem(ACCESS_TOKEN_KEY);
                }
                // Keep JWT UI in sync with auth state.
                if (typeof setJwtUiState === 'function') {
                    setJwtUiState();
                }
            }

            function setAuthStatus(message) {
                const el = document.getElementById('authStatus');
                if (el) el.textContent = message || '';
            }

            function setUserInfo(message) {
                const el = document.getElementById('userInfo');
                if (el) el.textContent = message || '';
            }

            function onAuthFailure(message, version = authVersion) {
                if (isStale(version)) return;
                // Token exists locally but is invalid/expired server-side.
                // Clear it to keep UI state consistent with the backend.
                bumpAuthVersion();
                setAccessToken(null);
                currentUserEmail = null;
                setUserInfo('');
                setAuthStatus(message || 'Session expired. Please sign in again.');
                const tasksDiv = document.getElementById('tasks');
                if (tasksDiv) tasksDiv.innerHTML = '<p>Not signed in. Click Sign in to load tasks.</p>';
                const tasksUpdated = document.getElementById('tasksUpdated');
                if (tasksUpdated) tasksUpdated.textContent = '';
                const scheduleDiv = document.getElementById('schedule');
                if (scheduleDiv) scheduleDiv.innerHTML = '';
            }

            function setJwtUiState() {
                const btn = document.getElementById('copyJwtBtn');
                const status = document.getElementById('jwtStatus');
                if (!btn || !status) return;

                const token = getAccessToken();
                if (token) {
                    btn.disabled = false;
                    status.textContent = 'JWT ready (copy-only)';
                } else {
                    btn.disabled = true;
                    status.textContent = 'Not signed in';
                }
            }

            async function copyJwt() {
                const status = document.getElementById('jwtStatus');
                const token = getAccessToken();
                if (!token) {
                    if (status) status.textContent = 'Not signed in';
                    return;
                }

                try {
                    if (navigator.clipboard && navigator.clipboard.writeText) {
                        await navigator.clipboard.writeText(token);
                    } else {
                        // Fallback for older browsers / non-clipboard contexts
                        const el = document.createElement('textarea');
                        el.value = token;
                        el.setAttribute('readonly', '');
                        el.style.position = 'absolute';
                        el.style.left = '-9999px';
                        document.body.appendChild(el);
                        el.select();
                        document.execCommand('copy');
                        document.body.removeChild(el);
                    }
                    if (status) status.textContent = 'JWT copied to clipboard';
                } catch (e) {
                    if (status) status.textContent = 'Copy failed';
                    console.error('Copy JWT failed:', e);
                }
            }

            async function apiFetch(path, options = {}, version = authVersion) {
                const token = getAccessToken();
                const headers = Object.assign({}, options.headers || {});
                if (token) {
                    headers['Authorization'] = `Bearer ${token}`;
                }
                const req = beginRequest(version);
                try {
                    const response = await fetch(path, Object.assign({}, options, { headers, signal: req.signal }));
                    if (response.status === 401 || response.status === 403) {
                        let detail = '';
                        try {
                            const err = await response.clone().json();
                            detail = (err && err.detail) ? String(err.detail) : '';
                        } catch (e) {
                            // ignore parse failure
                        }
                        const msg = detail || 'Session expired. Please sign in again.';
                        onAuthFailure(msg, version);
                        throw new Error(msg);
                    }
                    return response;
                } finally {
                    req.done();
                }
            }

            async function refreshMe(version = authVersion) {
                try {
                    const response = await apiFetch('/auth/me', {}, version);
                    const data = await response.json();
                    if (isStale(version)) return null;
                    const u = data.user || data;
                    if (u && u.email) {
                        currentUserEmail = u.email;
                        setUserInfo(`Signed in as ${u.email}`);
                    } else {
                        currentUserEmail = null;
                        setUserInfo('Signed in.');
                    }
                    return u;
                } catch (e) {
                    if (!isStale(version)) {
                        currentUserEmail = null;
                        setUserInfo('');
                    }
                    return null;
                }
            }

            function showSignedOutUi(message) {
                setAuthStatus(message || 'Not signed in.');
                setUserInfo('');
                setJwtUiState();
                const tasksDiv = document.getElementById('tasks');
                if (tasksDiv) tasksDiv.innerHTML = '<p>Sign in to load tasks.</p>';
                const tasksUpdated = document.getElementById('tasksUpdated');
                if (tasksUpdated) tasksUpdated.textContent = '';
                const scheduleDiv = document.getElementById('schedule');
                if (scheduleDiv) scheduleDiv.innerHTML = '';
                const shortcutStatus = document.getElementById('shortcutTokenStatus');
                if (shortcutStatus) shortcutStatus.textContent = '';
                const shortcutVal = document.getElementById('shortcutTokenValue');
                if (shortcutVal) shortcutVal.textContent = '';
            }

            async function syncSessionOnLoad() {
                const version = authVersion;
                if (!getAccessToken()) {
                    showSignedOutUi('Not signed in.');
                    return;
                }
                setAuthStatus('Checking session...');
                await refreshMe(version);
                if (isStale(version)) return;
                if (!getAccessToken()) {
                    // Token was cleared during refresh (expired/invalid)
                    showSignedOutUi('Session expired. Please sign in again.');
                    return;
                }
                setAuthStatus('Signed in.');
                await viewTasks(version);
                // Load schedule on refresh so it doesn't appear to "disappear".
                try { await viewSchedule(version); } catch (e) { /* ignore */ }
                await loadShortcutTokenStatus(version);
            }

            async function loadAuthConfig() {
                const res = await fetch('/auth/config');
                if (!res.ok) return null;
                return await res.json();
            }

            async function handleGoogleCredentialResponse(response) {
                try {
                    const preLoginVersion = authVersion;
                    setAuthStatus('Signing in...');
                    const idToken = response && response.credential;
                    if (!idToken) {
                        throw new Error('No Google ID token received.');
                    }

                    const res = await fetch('/auth/google/callback', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ id_token: idToken })
                    });

                    if (!res.ok) {
                        const err = await res.json().catch(() => ({}));
                        throw new Error(err.detail || 'Failed to authenticate');
                    }

                    const data = await res.json();
                    if (isStale(preLoginVersion)) return;
                    // Invalidate any in-flight requests tied to the old auth state.
                    bumpAuthVersion();
                    setAccessToken(data.access_token);
                    const version = authVersion;
                    setAuthStatus('Signed in.');
                    await refreshMe(version);
                    if (isStale(version)) return;
                    await viewTasks(version);
                    try { await viewSchedule(version); } catch (e) { /* ignore */ }
                    await loadShortcutTokenStatus(version);
                } catch (e) {
                    console.error('Auth error:', e);
                    setAuthStatus('Auth error: ' + (e && e.message ? e.message : String(e)));
                }
            }

            async function initGoogleSignIn() {
                const cfg = await loadAuthConfig();
                const clientId = cfg && cfg.google_oauth_client_id;
                if (!clientId) {
                    setAuthStatus('Missing GOOGLE_OAUTH_CLIENT_ID on the server. Set it in your .env and restart.');
                    return;
                }
                if (!window.google || !google.accounts || !google.accounts.id) {
                    setAuthStatus('Google sign-in library not loaded yet. Refresh in a second.');
                    return;
                }
                setJwtUiState();
                google.accounts.id.initialize({
                    client_id: clientId,
                    callback: handleGoogleCredentialResponse,
                    // Don't auto-select account - force user to choose
                    auto_select: false,
                    // Cancel One Tap prompt to force button click for account selection
                    cancel_on_tap_outside: true
                });
                google.accounts.id.renderButton(
                    document.getElementById("gsi-button"),
                    { 
                        theme: "outline", 
                        size: "large",
                        text: "signin_with",
                        shape: "rectangular"
                    }
                );
                // Don't auto-prompt - users must click the button to sign in.
                // Also: don't claim "Signed in" unless the backend validates the session.
                if (getAccessToken()) {
                    setAuthStatus('Checking session...');
                    await syncSessionOnLoad();
                } else {
                    showSignedOutUi('Not signed in.');
                }
            }

            function signOut() {
                // Ensure any in-flight requests can’t update the UI after logout.
                bumpAuthVersion();
                setAccessToken(null);
                setAuthStatus('Signed out.');
                setUserInfo('');
                try {
                    if (window.google && google.accounts && google.accounts.id) {
                        // Prevent Google from silently reusing the last account selection.
                        google.accounts.id.disableAutoSelect();
                        // Best-effort revoke; even if it fails, local logout still stands.
                        if (currentUserEmail) {
                            google.accounts.id.revoke(currentUserEmail, () => {});
                        }
                    }
                } catch (e) {
                    // ignore
                }
                currentUserEmail = null;
                document.getElementById('tasks').innerHTML = '<p>Signed out. Sign in to load tasks.</p>';
                const tasksUpdated = document.getElementById('tasksUpdated');
                if (tasksUpdated) tasksUpdated.textContent = '';
                document.getElementById('schedule').innerHTML = '';
                const shortcutStatus = document.getElementById('shortcutTokenStatus');
                if (shortcutStatus) shortcutStatus.textContent = '';
                const shortcutVal = document.getElementById('shortcutTokenValue');
                if (shortcutVal) shortcutVal.textContent = '';
            }

            async function loadShortcutTokenStatus(version = authVersion) {
                const el = document.getElementById('shortcutTokenStatus');
                const val = document.getElementById('shortcutTokenValue');
                val.textContent = '';
                try {
                    const res = await apiFetch('/auth/shortcut-token', {}, version);
                    const data = await res.json();
                    if (isStale(version)) return;
                    if (!data.active) {
                        el.textContent = 'No active shortcut token.';
                        return;
                    }
                    el.textContent = `Active token prefix: ${data.token_prefix || ''} (created ${data.created_at || ''})`;
                } catch (e) {
                    if (!isStale(version)) {
                        el.textContent = 'Error: ' + (e && e.message ? e.message : String(e));
                    }
                }
            }

            async function createShortcutToken(version = authVersion) {
                const el = document.getElementById('shortcutTokenStatus');
                const val = document.getElementById('shortcutTokenValue');
                val.textContent = '';
                try {
                    el.textContent = 'Creating token...';
                    const res = await apiFetch('/auth/shortcut-token', { method: 'POST' }, version);
                    const data = await res.json();
                    if (isStale(version)) return;
                    el.textContent = `Created token prefix: ${data.token_prefix}. Copy the token below (shown once).`;
                    val.textContent = data.token;
                } catch (e) {
                    if (!isStale(version)) {
                        el.textContent = 'Error: ' + (e && e.message ? e.message : String(e));
                    }
                }
            }

            async function revokeShortcutToken(version = authVersion) {
                const el = document.getElementById('shortcutTokenStatus');
                const val = document.getElementById('shortcutTokenValue');
                val.textContent = '';
                try {
                    el.textContent = 'Revoking token...';
                    await apiFetch('/auth/shortcut-token', { method: 'DELETE' }, version);
                    if (isStale(version)) return;
                    el.textContent = 'Token revoked.';
                } catch (e) {
                    if (!isStale(version)) {
                        el.textContent = 'Error: ' + (e && e.message ? e.message : String(e));
                    }
                }
            }

            async function createTask(event) {
                event.preventDefault();
                const version = authVersion;
                const status = document.getElementById('status');
                status.innerHTML = 'Creating task...';
                
                const taskData = {
                    title: document.getElementById('taskTitle').value,
                    notes: document.getElementById('taskNotes').value || null,
                    estimated_duration_min: parseInt(document.getElementById('taskDuration').value) || 30,
                    category: document.getElementById('taskCategory').value
                };
                
                try {
                    const response = await apiFetch('/tasks', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify(taskData)
                    }, version);
                    
                    if (!response.ok) {
                        const error = await response.json();
                        throw new Error(error.detail || 'Failed to create task');
                    }
                    
                    const data = await response.json();
                    if (isStale(version)) return;
                    status.innerHTML = `Task created: "${data.task.title}"`;
                    document.getElementById('createTaskForm').reset();
                    await viewTasks(version);
                } catch (error) {
                    if (!isStale(version)) {
                        status.innerHTML = 'Error: ' + error.message;
                    }
                }
            }
            
            async function importFromSheets(event) {
                event.preventDefault();
                const version = authVersion;
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
                    const response = await apiFetch(apiUrl, {
                        method: 'POST',
                        headers: { 
                            'Content-Type': 'application/json',
                            'Accept': 'application/json'
                        },
                        body: JSON.stringify(importData),
                        mode: 'cors',
                        credentials: 'same-origin'
                    }, version);
                    
                    if (!response.ok) {
                        const error = await response.json();
                        throw new Error(error.detail || 'Failed to import from Google Sheets');
                    }
                    
                    const data = await response.json();
                    if (isStale(version)) return;
                    status.innerHTML = `Imported ${data.imported_count} tasks${data.duplicates_detected > 0 ? ` (${data.duplicates_detected} duplicates detected)` : ''}`;
                    document.getElementById('importSheetsForm').reset();
                    await viewTasks(version);
                } catch (error) {
                    console.error('Import error:', error);
                    if (!isStale(version)) {
                        status.innerHTML = 'Error: ' + error.message + '. Check server console for details.';
                    }
                }
            }
            
            async function buildSchedule() {
                const version = authVersion;
                const status = document.getElementById('status');
                status.innerHTML = 'Building schedule...';
                try {
                    const response = await apiFetch('/schedule', { method: 'POST' }, version);
                    const data = await response.json();
                    if (isStale(version)) return;
                    status.innerHTML = `Schedule built: ${data.scheduled_blocks.length} blocks, ${data.overflow_tasks.length} overflow`;
                    await viewSchedule(version);
                } catch (error) {
                    if (!isStale(version)) {
                        status.innerHTML = 'Error: ' + error.message;
                    }
                }
            }
            
            function connectGoogleCalendar(version = authVersion) {
                return new Promise((resolve, reject) => {
                    if (isStale(version)) return reject(new Error('Auth changed; please try again.'));
                    // Important: popups can't attach Authorization headers to backend routes.
                    // Fetch the Google consent URL with JWT, then open Google directly.
                    apiFetch('/auth/google/calendar/auth-url', {}, version).then(async (res) => {
                        let payload = null;
                        try { payload = await res.json(); } catch (e) { /* ignore */ }
                        if (!res.ok) {
                            const detail = (payload && payload.detail) ? String(payload.detail) : `Failed to start calendar connect (HTTP ${res.status})`;
                            throw new Error(detail);
                        }
                        const url = payload && payload.url ? String(payload.url) : '';
                        if (!url) throw new Error('Missing calendar auth URL from server.');

                        const w = window.open(url, 'qz_google_calendar_oauth', 'width=520,height=700');
                        if (!w) throw new Error('Popup blocked. Please allow popups and try again.');

                        let done = false;
                        const cleanup = () => {
                            window.removeEventListener('message', onMessage);
                            clearInterval(poll);
                            done = true;
                            try { w.close(); } catch (e) { /* ignore */ }
                        };

                        const onMessage = (event) => {
                            const data = event && event.data;
                            if (data && data.type === 'qz_google_calendar_connected') {
                                cleanup();
                                resolve(true);
                            }
                        };

                        window.addEventListener('message', onMessage);
                        const poll = setInterval(() => {
                            if (done) return;
                            if (isStale(version)) {
                                cleanup();
                                reject(new Error('Auth changed; please try again.'));
                                return;
                            }
                            if (w.closed) {
                                cleanup();
                                reject(new Error('Google Calendar connection window was closed.'));
                            }
                        }, 500);
                    }).catch((e) => {
                        reject(e instanceof Error ? e : new Error(String(e)));
                    });
                });
            }

            async function syncCalendar() {
                const version = authVersion;
                const status = document.getElementById('status');
                status.innerHTML = 'Syncing to Google Calendar...';
                try {
                    // First attempt
                    let response = await apiFetch('/sync-calendar', { method: 'POST' }, version);
                    let data = null;
                    try { data = await response.clone().json(); } catch (e) { /* ignore */ }

                    if (!response.ok) {
                        const detail = (data && data.detail) ? String(data.detail) : `Sync failed (HTTP ${response.status})`;
                        const needsReconnect =
                            response.status === 400 &&
                            (detail.includes('Google Calendar not connected') ||
                             detail.includes('authorization expired') ||
                             detail.includes('expired or was revoked'));
                        if (needsReconnect) {
                            status.innerHTML = 'Connecting Google Calendar...';
                            await connectGoogleCalendar(version);
                            if (isStale(version)) return;
                            // Retry after connect
                            response = await apiFetch('/sync-calendar', { method: 'POST' }, version);
                            data = await response.json();
                            if (!response.ok) {
                                const retryDetail = (data && data.detail) ? String(data.detail) : `Sync failed (HTTP ${response.status})`;
                                throw new Error(retryDetail);
                            }
                        } else {
                            throw new Error(detail);
                        }
                    } else {
                        data = await response.json();
                    }
                    if (isStale(version)) return;
                    status.innerHTML = `Synced ${data.events_created} events to Google Calendar`;
                } catch (error) {
                    if (!isStale(version)) {
                        status.innerHTML = 'Error: ' + error.message;
                    }
                }
            }
            
            async function viewTasks(version = authVersion) {
                const tasksDiv = document.getElementById('tasks');
                try {
                    const tasksUpdated = document.getElementById('tasksUpdated');
                    if (tasksUpdated && !isStale(version)) tasksUpdated.textContent = 'Refreshing...';
                    const response = await apiFetch('/tasks', {}, version);
                    let data = null;
                    try {
                        data = await response.json();
                    } catch (e) {
                        // Non-JSON error response (or network issue)
                        throw new Error(`Failed to load tasks (HTTP ${response.status})`);
                    }
                    if (isStale(version)) return;

                    if (!response.ok) {
                        const detail = (data && data.detail) ? String(data.detail) : `Failed to load tasks (HTTP ${response.status})`;
                        throw new Error(detail);
                    }

                    if (!data || !Array.isArray(data.tasks)) {
                        throw new Error('Unexpected response from /tasks');
                    }
                    
                    if (data.tasks.length === 0) {
                        selectedTaskIds.clear();
                        lastRenderedTaskIds = [];
                        updateTaskSelectionUi();
                        tasksDiv.innerHTML = '<p>No tasks yet. Create a task or import from Google Sheets.</p>';
                        if (tasksUpdated) tasksUpdated.textContent = `Last refreshed: ${new Date().toLocaleString()}`;
                        return;
                    }
                    
                    lastRenderedTaskIds = (data.tasks || []).map(t => t.id);
                    // Drop any selections that are no longer visible
                    selectedTaskIds = new Set(Array.from(selectedTaskIds).filter(id => lastRenderedTaskIds.includes(id)));

                    let html = `<p><strong>Total tasks: ${data.count}</strong></p>`;
                    html += '<div class="tasks-container"><table><tr><th class="select-col">Sel</th><th>Title</th><th>Category</th><th>Duration</th><th>Status</th><th>Notes</th></tr>';
                    data.tasks.forEach(task => {
                        const notes = task.notes ? task.notes.replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;').replace(/'/g, '&#39;') : '';
                        const checked = selectedTaskIds.has(task.id) ? 'checked' : '';
                        html += `<tr>
                            <td class="select-col"><input type="checkbox" class="task-select" ${checked} onchange="toggleTaskSelection('${task.id}', this.checked)"></td>
                            <td>${task.title}</td>
                            <td>${task.category || 'N/A'}</td>
                            <td>${task.estimated_duration_min || 30} min</td>
                            <td>${task.status || 'OPEN'}</td>
                            <td class="notes">${notes || 'N/A'}</td>
                        </tr>`;
                    });
                    html += '</table></div>';

                    html += `
                        <div class="tasks-actions-bottom">
                            <button onclick="deleteSelectedTasks()">Delete selected</button>
                            <button onclick="purgeSelectedTasks()">Purge selected</button>
                        </div>
                    `;
                    
                    tasksDiv.innerHTML = html;
                    updateTaskSelectionUi();
                    if (tasksUpdated) tasksUpdated.textContent = `Last refreshed: ${new Date().toLocaleString()}`;
                } catch (error) {
                    if (isStale(version)) return;
                    tasksDiv.innerHTML = 'Error: ' + error.message;
                    const tasksUpdated = document.getElementById('tasksUpdated');
                    if (tasksUpdated) tasksUpdated.textContent = 'Refresh failed.';
                }
            }

            let selectedTaskIds = new Set();
            let lastRenderedTaskIds = [];

            function updateTaskSelectionUi() {
                const selectAll = document.getElementById('selectAllTasks');
                if (selectAll) {
                    const total = lastRenderedTaskIds.length;
                    const selected = selectedTaskIds.size;
                    selectAll.checked = total > 0 && selected === total;
                    selectAll.indeterminate = selected > 0 && selected < total;
                }
            }

            function toggleTaskSelection(taskId, checked) {
                if (checked) selectedTaskIds.add(taskId);
                else selectedTaskIds.delete(taskId);
                updateTaskSelectionUi();
            }

            function toggleSelectAllTasks(checked) {
                if (checked) {
                    lastRenderedTaskIds.forEach(id => selectedTaskIds.add(id));
                } else {
                    lastRenderedTaskIds.forEach(id => selectedTaskIds.delete(id));
                }
                // Update visible checkboxes without refetching
                const boxes = document.querySelectorAll('input.task-select');
                boxes.forEach(b => { b.checked = checked; });
                updateTaskSelectionUi();
            }

            async function deleteSelectedTasks() {
                const version = authVersion;
                const status = document.getElementById('status');
                const ids = Array.from(selectedTaskIds);
                if (ids.length === 0) {
                    status.innerHTML = 'No tasks selected.';
                    return;
                }
                if (!confirm(`Delete ${ids.length} selected task(s)? (Undoable via restore endpoint)`)) return;
                try {
                    status.innerHTML = 'Deleting selected tasks...';
                    const response = await apiFetch('/tasks/bulk_delete', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ task_ids: ids }),
                    }, version);
                    const data = await response.json();
                    if (isStale(version)) return;
                    selectedTaskIds.clear();
                    status.innerHTML = `Deleted ${data.affected_count} task(s).` + (data.not_found_ids && data.not_found_ids.length ? ` Not found: ${data.not_found_ids.length}.` : '');
                    await viewTasks(version);
                } catch (e) {
                    if (!isStale(version)) status.innerHTML = 'Error: ' + (e && e.message ? e.message : String(e));
                }
            }

            async function purgeSelectedTasks() {
                const version = authVersion;
                const status = document.getElementById('status');
                const ids = Array.from(selectedTaskIds);
                if (ids.length === 0) {
                    status.innerHTML = 'No tasks selected.';
                    return;
                }
                if (!confirm(`Purge ${ids.length} selected task(s)? This is irreversible.`)) return;
                try {
                    status.innerHTML = 'Purging selected tasks...';
                    const response = await apiFetch('/tasks/bulk_purge', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ task_ids: ids }),
                    }, version);
                    const data = await response.json();
                    if (isStale(version)) return;
                    selectedTaskIds.clear();
                    status.innerHTML = `Purged ${data.affected_count} task(s).` + (data.not_found_ids && data.not_found_ids.length ? ` Not found: ${data.not_found_ids.length}.` : '');
                    await viewTasks(version);
                } catch (e) {
                    if (!isStale(version)) status.innerHTML = 'Error: ' + (e && e.message ? e.message : String(e));
                }
            }
            
            async function viewSchedule(version = authVersion) {
                const scheduleDiv = document.getElementById('schedule');
                try {
                    const response = await apiFetch('/schedule', {}, version);
                    const data = await response.json();
                    if (isStale(version)) return;
                    
                    if (data.scheduled_blocks.length === 0) {
                        scheduleDiv.innerHTML = '<p>No schedule available. Build a schedule first.</p>';
                        return;
                    }
                    
                    let html = '<table><tr><th>Start</th><th>End</th><th>Task</th><th>Freeze</th></tr>';
                    data.scheduled_blocks.forEach(block => {
                        let taskName = 'Unknown';
                        if (block.entity_type === 'task' && data.task_titles && data.task_titles[block.entity_id]) {
                            taskName = data.task_titles[block.entity_id];
                        } else if (block.entity_type === 'transition') {
                            taskName = 'Transition';
                        } else {
                            taskName = block.entity_id; // Fallback to ID if title not found
                        }
                        const checked = block.locked ? 'checked' : '';
                        html += `<tr>
                            <td>${new Date(block.start_time).toLocaleString()}</td>
                            <td>${new Date(block.end_time).toLocaleString()}</td>
                            <td>${taskName}</td>
                            <td><input type="checkbox" ${checked} onchange="toggleFreeze('${block.id}', this.checked)"></td>
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
                    if (isStale(version)) return;
                    // Treat "no schedule" as a normal empty state, not an error.
                    const msg = error && error.message ? String(error.message) : String(error);
                    if (msg && msg.toLowerCase().includes('no schedule available')) {
                        scheduleDiv.innerHTML = '<p>No schedule available. Build a schedule first.</p>';
                        return;
                    }
                    scheduleDiv.innerHTML = 'Error: ' + msg;
                }
            }

            async function toggleFreeze(blockId, checked) {
                const version = authVersion;
                const status = document.getElementById('status');
                try {
                    status.innerHTML = checked ? 'Freezing block...' : 'Unfreezing block...';
                    const path = checked ? `/schedule/blocks/${blockId}/lock` : `/schedule/blocks/${blockId}/unlock`;
                    const response = await apiFetch(path, { method: 'POST' }, version);
                    let data = null;
                    try { data = await response.json(); } catch (e) { /* ignore */ }
                    if (!response.ok) {
                        const detail = (data && data.detail) ? String(data.detail) : `Failed (HTTP ${response.status})`;
                        throw new Error(detail);
                    }
                    if (isStale(version)) return;
                    status.innerHTML = checked ? 'Block frozen.' : 'Block unfrozen.';
                    await viewSchedule(version);
                } catch (e) {
                    if (!isStale(version)) status.innerHTML = 'Error: ' + (e && e.message ? e.message : String(e));
                    // Refresh schedule to revert UI checkbox to server state.
                    try { await viewSchedule(version); } catch (_) { /* ignore */ }
                }
            }
            
            // Load tasks on page load
            window.onload = async function() {
                await initGoogleSignIn();
                // initGoogleSignIn() calls syncSessionOnLoad() when a token exists.
                // If not signed in, it will show signed-out UI.
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


# Frontend config (safe to expose)
@app.get("/auth/config")
async def auth_config():
    """Return public auth configuration needed by the browser UI."""
    return {"google_oauth_client_id": os.getenv("GOOGLE_OAUTH_CLIENT_ID", "")}


# Authentication endpoints
@app.post("/auth/google/callback", response_model=AuthResponse)
async def google_oauth_callback(
    request: GoogleOAuthCallbackRequest,
    db: Session = Depends(get_db)
):
    """Handle Google OAuth callback and create/login user.
    
    Expected request body:
    {
        "id_token": "Google ID token from OAuth flow"
    }
    
    Returns JWT token for authenticated user.
    """
    # Verify Google token and get user info
    user_info = verify_google_token(request.id_token)
    if not user_info:
        raise HTTPException(status_code=401, detail="Invalid Google token")
    
    if not user_info.get('email'):
        raise HTTPException(status_code=400, detail="Email is required")
    
    # Create or update user in database
    user_repo = UserRepository(db)
    now = datetime.utcnow()
    user = User(
        id=user_info['id'],
        email=user_info['email'],
        name=user_info.get('name'),
        created_at=now,
        updated_at=now,
    )
    
    try:
        user = user_repo.create_or_update(user)
    except Exception as e:
        logger.error(f"Failed to create/update user: {type(e).__name__}: {str(e)}")
        raise HTTPException(status_code=500, detail="Failed to create/update user")

    # Legacy DB compatibility: if tasks were created before multi-user support,
    # they may have NULL user_id. Claim unowned tasks for this user so they
    # remain visible after login.
    try:
        db.execute(
            text("UPDATE tasks SET user_id = :uid WHERE user_id IS NULL OR user_id = ''"),
            {"uid": user.id},
        )
        db.commit()
    except Exception as e:
        db.rollback()
        logger.warning(f"Failed to claim legacy tasks for user {user.id}: {type(e).__name__}: {str(e)}")
    
    # Generate JWT token
    token = create_access_token(user.id)
    
    return AuthResponse(
        access_token=token,
        token_type="bearer",
        user=user.model_dump()
    )


@app.get("/auth/me")
async def get_current_user_info(current_user: User = Depends(get_current_user)):
    """Get current authenticated user information."""
    return {"user": current_user.model_dump()}


@app.get("/auth/google/calendar/start")
async def google_calendar_oauth_start(
    request: Request,
    current_user: User = Depends(get_current_user),
):
    """Start per-user Google Calendar OAuth (authorization code flow).

    This is required for deployed environments (Cloud Run); do not use server-local OAuth flows.
    """
    client_id = os.getenv("GOOGLE_OAUTH_CLIENT_ID", "").strip()
    client_secret = os.getenv("GOOGLE_OAUTH_CLIENT_SECRET", "").strip()
    if not client_id or not client_secret:
        raise HTTPException(status_code=500, detail="Google OAuth client is not configured")

    redirect_uri = _public_url_for(request, "google_calendar_oauth_callback")
    state = _encode_calendar_oauth_state(current_user.id)

    auth_url = "https://accounts.google.com/o/oauth2/v2/auth"
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "https://www.googleapis.com/auth/calendar",
        "access_type": "offline",
        # Force account chooser + consent so Google reliably returns a refresh_token on reconnect.
        "prompt": "consent select_account",
        "include_granted_scopes": "true",
        "state": state,
    }

    return RedirectResponse(url=f"{auth_url}?{urlencode(params)}", status_code=302)


@app.get("/auth/google/calendar/auth-url")
async def google_calendar_oauth_auth_url(
    request: Request,
    current_user: User = Depends(get_current_user),
):
    """Return the Google consent URL for Calendar connect (JSON).

    This exists because browser popups can't attach Authorization headers to server routes.
    The UI fetches this URL (with JWT) then opens the returned Google URL in a popup.
    """
    client_id = os.getenv("GOOGLE_OAUTH_CLIENT_ID", "").strip()
    client_secret = os.getenv("GOOGLE_OAUTH_CLIENT_SECRET", "").strip()
    if not client_id or not client_secret:
        raise HTTPException(status_code=500, detail="Google OAuth client is not configured")

    redirect_uri = _public_url_for(request, "google_calendar_oauth_callback")
    state = _encode_calendar_oauth_state(current_user.id)

    auth_url = "https://accounts.google.com/o/oauth2/v2/auth"
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": "https://www.googleapis.com/auth/calendar",
        "access_type": "offline",
        # Force account chooser + consent so Google reliably returns a refresh_token on reconnect.
        "prompt": "consent select_account",
        "include_granted_scopes": "true",
        "state": state,
    }
    return {"url": f"{auth_url}?{urlencode(params)}"}


@app.get("/auth/google/calendar/callback", name="google_calendar_oauth_callback")
async def google_calendar_oauth_callback(
    request: Request,
    code: Optional[str] = Query(default=None),
    state: Optional[str] = Query(default=None),
    error: Optional[str] = Query(default=None),
    error_description: Optional[str] = Query(default=None),
    db: Session = Depends(get_db),
):
    """OAuth callback that exchanges code for tokens and stores refresh token encrypted."""
    if error:
        msg = error_description or error
        return HTMLResponse(
            f"""<!doctype html>
<html><body>
<h3>Google Calendar connection failed</h3>
<p>{msg}</p>
</body></html>""",
            status_code=400,
        )

    if not code or not state:
        raise HTTPException(status_code=400, detail="Missing OAuth code/state")

    user_id = _decode_calendar_oauth_state(state)

    client_id = os.getenv("GOOGLE_OAUTH_CLIENT_ID", "").strip()
    client_secret = os.getenv("GOOGLE_OAUTH_CLIENT_SECRET", "").strip()
    if not client_id or not client_secret:
        raise HTTPException(status_code=500, detail="Google OAuth client is not configured")

    redirect_uri = _public_url_for(request, "google_calendar_oauth_callback")

    token_url = "https://oauth2.googleapis.com/token"
    token_resp = requests.post(
        token_url,
        data={
            "client_id": client_id,
            "client_secret": client_secret,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": redirect_uri,
        },
        timeout=15,
    )

    try:
        token_data = token_resp.json()
    except Exception:
        raise HTTPException(status_code=502, detail="Failed to parse Google token response")

    if not token_resp.ok:
        err = token_data.get("error_description") or token_data.get("error") or "Google token exchange failed"
        raise HTTPException(status_code=502, detail=str(err))

    refresh_token = token_data.get("refresh_token")
    access_token = token_data.get("access_token")
    expires_in = token_data.get("expires_in")
    scope_str = token_data.get("scope") or ""
    scopes = [s for s in scope_str.split() if s] or ["https://www.googleapis.com/auth/calendar"]

    repo = GoogleOAuthTokenRepository(db)
    if not refresh_token:
        # Google may omit refresh_token on subsequent grants.
        existing = repo.get_google_calendar(user_id)
        if not existing:
            raise HTTPException(
                status_code=400,
                detail="Google did not return a refresh token. Please revoke app access in your Google Account and try again.",
            )
        # Keep existing refresh token only if it is still valid (not revoked).
        try:
            existing_refresh = decrypt_secret(existing.refresh_token_encrypted)
            test_creds = GoogleCredentials(
                token=None,
                refresh_token=existing_refresh,
                token_uri="https://oauth2.googleapis.com/token",
                client_id=client_id,
                client_secret=client_secret,
                scopes=scopes,
            )
            test_creds.refresh(GoogleAuthRequest())
        except Exception:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Google did not return a refresh token, and your existing Calendar authorization is no longer valid. "
                    "Please revoke qzWhatNext access in your Google Account (Security → Third-party access) and try again."
                ),
            )
        html = """<!doctype html>
<html><body>
<script>
  (function () {
    try { if (window.opener) window.opener.postMessage({type: 'qz_google_calendar_connected'}, '*'); } catch (e) {}
    try { window.close(); } catch (e) {}
  })();
</script>
<p>Google Calendar is already connected. You can close this window.</p>
</body></html>"""
        return HTMLResponse(html, status_code=200)

    expiry = None
    if isinstance(expires_in, (int, float)):
        expiry = datetime.utcnow() + timedelta(seconds=int(expires_in))

    repo.upsert_google_calendar(
        user_id=user_id,
        refresh_token=str(refresh_token),
        scopes=scopes,
        access_token=str(access_token) if access_token else None,
        expiry=expiry,
    )

    html = """<!doctype html>
<html><body>
<script>
  (function () {
    try { if (window.opener) window.opener.postMessage({type: 'qz_google_calendar_connected'}, '*'); } catch (e) {}
    try { window.close(); } catch (e) {}
  })();
</script>
<p>Google Calendar connected. You can close this window.</p>
</body></html>"""
    return HTMLResponse(html, status_code=200)


@app.get("/auth/shortcut-token", response_model=ShortcutTokenStatusResponse)
async def get_shortcut_token_status(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Get shortcut token status for the current user (does not reveal the token)."""
    token_db = (
        db.query(ApiTokenDB)
        .filter(ApiTokenDB.user_id == current_user.id, ApiTokenDB.revoked_at.is_(None))
        .order_by(ApiTokenDB.created_at.desc())
        .first()
    )
    if not token_db:
        return ShortcutTokenStatusResponse(active=False)
    return ShortcutTokenStatusResponse(
        active=True,
        token_prefix=token_db.token_prefix,
        created_at=token_db.created_at,
        last_used_at=token_db.last_used_at,
    )


@app.post("/auth/shortcut-token", response_model=ShortcutTokenCreateResponse)
async def create_shortcut_token(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Create (or rotate) a shortcut token for the current user.

    The raw token is returned ONCE. Store it in your iOS Shortcut.
    """
    # Revoke any existing active tokens for this user (single active token policy).
    now = datetime.utcnow()
    db.query(ApiTokenDB).filter(
        ApiTokenDB.user_id == current_user.id,
        ApiTokenDB.revoked_at.is_(None),
    ).update({"revoked_at": now})
    db.commit()

    token = generate_shortcut_token()
    token_prefix = token[:6]
    token_hash = hash_shortcut_token(token)

    token_db = ApiTokenDB(
        user_id=current_user.id,
        token_hash=token_hash,
        token_prefix=token_prefix,
        name="ios_shortcut",
        created_at=now,
    )
    db.add(token_db)
    db.commit()

    return ShortcutTokenCreateResponse(token=token, token_prefix=token_prefix, created_at=now)


@app.delete("/auth/shortcut-token", status_code=204)
async def revoke_shortcut_token(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Revoke the current user's active shortcut token(s)."""
    now = datetime.utcnow()
    db.query(ApiTokenDB).filter(
        ApiTokenDB.user_id == current_user.id,
        ApiTokenDB.revoked_at.is_(None),
    ).update({"revoked_at": now})
    db.commit()
    return Response(status_code=204)


# Task CRUD endpoints
@app.post("/tasks", response_model=TaskResponse, status_code=201)
async def create_task(
    request: TaskCreateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Create a new task."""
    repo = TaskRepository(db)
    
    # Check for duplicates if source_id is provided
    if request.source_id:
        duplicates = repo.find_duplicates(current_user.id, request.source_type, request.source_id, request.title)
        if duplicates:
            # For MVP, we just log but still create (no auto-dedupe)
            logger.warning(
                f"Potential duplicate task detected: source_type={request.source_type}, "
                f"source_id={request.source_id}, title={request.title[:50]}, "
                f"found {len(duplicates)} existing task(s)"
            )
    
    # Create task using factory (applies defaults from constants)
    task = create_task_base(
        user_id=current_user.id,
        source_type=request.source_type,
        source_id=request.source_id,
        title=request.title,
        notes=request.notes,
        deadline=request.deadline,
        estimated_duration_min=request.estimated_duration_min,
        category=request.category,
        ai_excluded=determine_ai_exclusion(request.title) if request.title else False,
    )
    
    try:
        created_task = repo.create(task)
        return TaskResponse(task=created_task)
    except Exception as e:
        logger.error(f"Failed to create task: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to create task: {str(e)}")


@app.post("/tasks/add_smart", response_model=TaskResponse, status_code=201)
async def add_smart_task(
    request: TaskAddSmartRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Create a new task from iOS Shortcut with auto-generated title and category.
    
    This endpoint is designed for iOS Shortcuts integration. It accepts only
    a notes field and automatically generates:
    - Task title from notes using OpenAI API (or truncates notes as fallback)
    - Category from notes using OpenAI API (if not AI-excluded)
    
    If notes start with ".", the task is AI-excluded and uses fallback title generation.
    """
    
    repo = TaskRepository(db)
    
    # Check if notes starts with "." for AI exclusion
    ai_excluded = request.notes.startswith('.') if request.notes else False
    
    # Determine title: try AI generation if not excluded, otherwise use fallback
    task_title = ""
    notes = request.notes or ""
    
    # Generate title if not AI-excluded
    if not ai_excluded and notes.strip():
        # Create temporary task object for inference (minimal fields needed)
        # Use factory but override title to empty string to avoid AI exclusion check
        temp_task = create_task_base(
            user_id=current_user.id,
            source_type="api",
            source_id=None,
            title="",  # Empty title won't trigger AI exclusion check
            notes=notes,
            ai_excluded=False,  # We already checked this above
        )
        
        try:
            generated_title = generate_title(temp_task, max_length=100)
            if generated_title and generated_title.strip():
                task_title = generated_title.strip()
                logger.debug(f"Generated title for task: {task_title[:50]}...")
        except Exception as e:
            # Log error but don't fail task creation
            logger.error(f"Error generating title: {type(e).__name__}")
            # Fall through to fallback
    
    # Fallback: use first 100 characters of notes, or default if empty
    if not task_title:
        if notes.strip():
            task_title = notes[:100].strip()
            if len(notes) > 100:
                # Truncate at word boundary if possible
                truncated = task_title.rsplit(' ', 1)[0] if ' ' in task_title else task_title
                task_title = truncated if len(truncated) > 50 else task_title  # Keep at least 50 chars if possible
        else:
            task_title = "Untitled Task"
    
    # Create task with generated/fallback title using factory
    task = create_task_base(
        user_id=current_user.id,
        source_type="api",
        source_id=None,
        title=task_title,
        notes=request.notes,
        ai_excluded=ai_excluded,
    )
    
    # Infer category and duration if not AI-excluded
    if not ai_excluded:
        try:
            inferred_category, category_confidence = infer_category(task)
            # Update category if confidence meets threshold
            # (infer_category already applies threshold, so if it returns non-UNKNOWN, use it)
            if inferred_category != TaskCategory.UNKNOWN:
                task.category = inferred_category
                logger.debug(f"Task {task.id} category inferred as {inferred_category.value} with confidence {category_confidence}")
            else:
                logger.debug(f"Task {task.id} category inference returned UNKNOWN (confidence: {category_confidence})")
        except Exception as e:
            # Log error but don't fail task creation
            logger.error(f"Error inferring category for task {task.id}: {type(e).__name__}")
            # Continue with UNKNOWN category
        
        # Estimate duration
        try:
            estimated_duration, duration_confidence = estimate_duration(task)
            # Update duration if estimation succeeds (returns duration > 0 and confidence >= threshold)
            # (estimate_duration already applies threshold and constraints, so if it returns non-zero, use it)
            if estimated_duration > 0:
                task.estimated_duration_min = estimated_duration
                task.duration_confidence = duration_confidence
                logger.debug(f"Task {task.id} duration estimated as {estimated_duration} minutes with confidence {duration_confidence}")
            else:
                logger.debug(f"Task {task.id} duration estimation returned 0 (failed or below threshold)")
                # Keep default 30 minutes with 0.5 confidence
        except Exception as e:
            # Log error but don't fail task creation
            logger.error(f"Error estimating duration for task {task.id}: {type(e).__name__}")
            # Continue with default 30 minutes
    
    try:
        created_task = repo.create(task)
        return TaskResponse(task=created_task)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to create task: {str(e)}")


@app.get("/tasks", response_model=TaskListResponse)
async def list_tasks(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """List all tasks for current user."""
    repo = TaskRepository(db)
    try:
        tasks = repo.get_all(current_user.id)
        return TaskListResponse(tasks=tasks, count=len(tasks))
    except Exception as e:
        logger.error(f"Failed to list tasks: {type(e).__name__}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to list tasks: {str(e)}")


@app.get("/tasks/{task_id}", response_model=TaskResponse)
async def get_task(
    task_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Get a task by ID."""
    repo = TaskRepository(db)
    task = repo.get(current_user.id, task_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")
    return TaskResponse(task=task)


@app.put("/tasks/{task_id}", response_model=TaskResponse)
async def update_task(
    task_id: str,
    request: TaskUpdateRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Update a task."""
    repo = TaskRepository(db)
    task = repo.get(current_user.id, task_id)
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
    except ValueError as e:
        # ValueError from repository means task not found
        logger.warning(f"Task {task_id} not found for update")
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Failed to update task {task_id}: {type(e).__name__}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to update task: {str(e)}")


@app.delete("/tasks/{task_id}", status_code=204)
async def delete_task(
    task_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Soft-delete a task (undoable via restore)."""
    repo = TaskRepository(db)
    schedule_repo = ScheduledBlockRepository(db)
    success = repo.delete(current_user.id, task_id)
    if not success:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")

    # Ensure schedule doesn't reference deleted tasks
    schedule_repo.delete_task_blocks(current_user.id, [task_id])
    return None


@app.post("/tasks/{task_id}/restore", response_model=TaskResponse)
async def restore_task(
    task_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Restore a soft-deleted task."""
    repo = TaskRepository(db)
    success = repo.restore(current_user.id, task_id)
    if not success:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")

    # Return the active task
    task = repo.get(current_user.id, task_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")
    return TaskResponse(task=task)


@app.delete("/tasks/{task_id}/purge", status_code=204)
async def purge_task(
    task_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Permanently delete a task (irreversible)."""
    repo = TaskRepository(db)
    schedule_repo = ScheduledBlockRepository(db)
    success = repo.purge(current_user.id, task_id)
    if not success:
        raise HTTPException(status_code=404, detail=f"Task {task_id} not found")

    # Ensure schedule doesn't reference deleted tasks
    schedule_repo.delete_task_blocks(current_user.id, [task_id])
    return None


@app.post("/tasks/bulk_delete", response_model=BulkActionResponse)
async def bulk_delete_tasks(
    request: BulkTaskIdsRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Soft-delete multiple tasks (undoable via bulk restore)."""
    repo = TaskRepository(db)
    schedule_repo = ScheduledBlockRepository(db)
    result = repo.bulk_delete(current_user.id, request.task_ids)
    # Ensure schedule doesn't reference deleted tasks
    if result.get("affected_count", 0) > 0:
        schedule_repo.delete_task_blocks(current_user.id, request.task_ids)
    return BulkActionResponse(**result)


@app.post("/tasks/bulk_restore", response_model=BulkActionResponse)
async def bulk_restore_tasks(
    request: BulkTaskIdsRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Restore multiple soft-deleted tasks."""
    repo = TaskRepository(db)
    result = repo.bulk_restore(current_user.id, request.task_ids)
    return BulkActionResponse(**result)


@app.post("/tasks/bulk_purge", response_model=BulkActionResponse)
async def bulk_purge_tasks(
    request: BulkTaskIdsRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Permanently delete multiple tasks (irreversible)."""
    repo = TaskRepository(db)
    schedule_repo = ScheduledBlockRepository(db)
    result = repo.bulk_purge(current_user.id, request.task_ids)
    # Ensure schedule doesn't reference deleted tasks
    if result.get("affected_count", 0) > 0:
        schedule_repo.delete_task_blocks(current_user.id, request.task_ids)
    return BulkActionResponse(**result)


# Google Sheets import endpoint
@app.post("/import/sheets", response_model=ImportSheetsResponse)
async def import_from_sheets(
    request: ImportSheetsRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
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
            user_id=current_user.id,
            spreadsheet_id=request.spreadsheet_id,
            range_name=request.range_name,
            has_header=request.has_header
        )
        
        # Save tasks to database and detect duplicates
        saved_tasks = []
        duplicates_count = 0
        
        for task in imported_tasks:
            # Check for duplicates
            duplicates = repo.find_duplicates(current_user.id, task.source_type, task.source_id, task.title)
            if duplicates:
                duplicates_count += 1
                # For MVP: notify user but still import (no auto-dedupe)
            
            # Create task in database
            try:
                created_task = repo.create(task)
                saved_tasks.append(created_task)
            except Exception as e:
                # Log error but continue with other tasks
                logger.error(f"Error saving task '{task.title[:50]}': {type(e).__name__}: {str(e)}")
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
async def build_schedule(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Build schedule from tasks in database."""
    task_repo = TaskRepository(db)
    schedule_repo = ScheduledBlockRepository(db)
    
    tasks = task_repo.get_open(current_user.id)
    
    if not tasks:
        raise HTTPException(status_code=400, detail="No tasks available. Create tasks first.")
    
    try:
        # Preserve locked blocks from prior schedule (frozen placements).
        existing_blocks = schedule_repo.get_all(current_user.id)
        locked_blocks = [b for b in existing_blocks if b.locked]
        unlocked_blocks = [b for b in existing_blocks if not b.locked]

        # Preserve calendar_event_id mappings across rebuild by reusing prior block IDs per-task.
        # This prevents duplicate calendar events when schedule is rebuilt.
        unlocked_by_task: Dict[str, List[ScheduledBlock]] = {}
        for b in unlocked_blocks:
            if b.entity_type == "task":
                unlocked_by_task.setdefault(b.entity_id, []).append(b)
        for tid in unlocked_by_task:
            unlocked_by_task[tid].sort(key=lambda b: b.start_time)

        # Compute reserved intervals (locked time is off-limits for new blocks).
        reserved_intervals = [(b.start_time, b.end_time) for b in locked_blocks]

        # Reduce per-task remaining duration by time already covered by locked blocks.
        locked_minutes_by_task: Dict[str, int] = {}
        for b in locked_blocks:
            if b.entity_type == "task":
                mins = int((b.end_time - b.start_time).total_seconds() // 60)
                locked_minutes_by_task[b.entity_id] = locked_minutes_by_task.get(b.entity_id, 0) + max(mins, 0)

        # Stack rank tasks
        ranked_tasks = stack_rank(tasks)

        # Schedule remaining work around locked placements.
        schedulable_tasks: List[Task] = []
        for t in ranked_tasks:
            consumed = locked_minutes_by_task.get(t.id, 0)
            remaining = max(int(t.estimated_duration_min) - consumed, 0)
            if remaining <= 0:
                continue
            schedulable_tasks.append(t.model_copy(update={"estimated_duration_min": remaining}))

        schedule_result = schedule_tasks(schedulable_tasks, reserved_intervals=reserved_intervals)

        # Reuse unlocked block IDs + calendar sync metadata where possible (per task, by block order).
        adjusted_blocks: List[ScheduledBlock] = []
        new_by_task: Dict[str, List[ScheduledBlock]] = {}
        for b in schedule_result.scheduled_blocks:
            if b.entity_type == "task":
                new_by_task.setdefault(b.entity_id, []).append(b)
            else:
                adjusted_blocks.append(b)
        for tid in new_by_task:
            new_by_task[tid].sort(key=lambda b: b.start_time)
            prior = unlocked_by_task.get(tid, [])
            for i, b in enumerate(new_by_task[tid]):
                if i < len(prior):
                    old = prior[i]
                    b = b.model_copy(
                        update={
                            "id": old.id,
                            "calendar_event_id": old.calendar_event_id,
                            "calendar_event_etag": getattr(old, "calendar_event_etag", None),
                            "calendar_event_updated_at": getattr(old, "calendar_event_updated_at", None),
                        }
                    )
                adjusted_blocks.append(b)
        schedule_result.scheduled_blocks = adjusted_blocks

        # Store schedule in database (preserve locked, replace unlocked)
        schedule_repo.delete_unlocked_for_user(current_user.id)
        schedule_repo.create_batch(schedule_result.scheduled_blocks)

        # Combined view: locked blocks + newly scheduled blocks
        combined_blocks = sorted(locked_blocks + schedule_result.scheduled_blocks, key=lambda b: b.start_time)
        
        # Build task titles map for frontend lookup
        task_titles = _build_task_titles_dict(tasks, combined_blocks)
        
        return ScheduleResponse(
            scheduled_blocks=combined_blocks,
            overflow_tasks=schedule_result.overflow_tasks,
            start_time=schedule_result.start_time,
            task_titles=task_titles
        )
    except Exception as e:
        logger.error(f"Failed to build schedule: {type(e).__name__}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to build schedule: {str(e)}")


@app.get("/schedule", response_model=ScheduleResponse)
async def view_schedule(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """View current schedule for user."""
    schedule_repo = ScheduledBlockRepository(db)
    task_repo = TaskRepository(db)
    
    blocks = schedule_repo.get_all(current_user.id)
    
    if not blocks:
        raise HTTPException(status_code=404, detail="No schedule available. Build a schedule first.")
    
    tasks = task_repo.get_all(current_user.id)
    task_titles = _build_task_titles_dict(tasks, blocks)
    
    # For MVP, overflow_tasks and start_time are not stored in DB
    # Return empty overflow and None start_time
    return ScheduleResponse(
        scheduled_blocks=blocks,
        overflow_tasks=[],
        start_time=None,
        task_titles=task_titles
    )


@app.post("/sync-calendar", response_model=SyncResponse)
async def sync_calendar(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Sync schedule to Google Calendar."""
    schedule_repo = ScheduledBlockRepository(db)
    task_repo = TaskRepository(db)
    
    blocks = schedule_repo.get_all(current_user.id)
    
    if not blocks:
        raise HTTPException(status_code=400, detail="No schedule available. Build a schedule first.")
    
    try:
        token_repo = GoogleOAuthTokenRepository(db)
        token_row = token_repo.get_google_calendar(current_user.id)
        if not token_row:
            raise HTTPException(
                status_code=400,
                detail="Google Calendar not connected. Connect via /auth/google/calendar/auth-url (or click Sync in the UI).",
            )

        client_id = os.getenv("GOOGLE_OAUTH_CLIENT_ID", "").strip()
        client_secret = os.getenv("GOOGLE_OAUTH_CLIENT_SECRET", "").strip()
        if not client_id or not client_secret:
            raise HTTPException(status_code=500, detail="Google OAuth client is not configured")

        refresh_token = decrypt_secret(token_row.refresh_token_encrypted)
        scopes = token_row.scopes or ["https://www.googleapis.com/auth/calendar"]

        creds = GoogleCredentials(
            token=None,
            refresh_token=refresh_token,
            token_uri="https://oauth2.googleapis.com/token",
            client_id=client_id,
            client_secret=client_secret,
            scopes=scopes,
        )
        try:
            creds.refresh(GoogleAuthRequest())
        except Exception as e:
            logger.warning(f"Google Calendar refresh failed for user {current_user.id}: {type(e).__name__}: {str(e)}")
            # If the refresh token is revoked/expired, clear it so the next sync forces reconnect.
            msg = str(e).lower()
            if "invalid_grant" in msg or "expired" in msg or "revoked" in msg:
                try:
                    token_repo.delete_google_calendar(current_user.id)
                except Exception:
                    # Best effort; never hide the original auth failure.
                    pass
            raise HTTPException(
                status_code=400,
                detail=(
                    "Google Calendar authorization expired or was revoked. "
                    "Reconnect via /auth/google/calendar/auth-url (or click Sync in the UI)."
                ),
            )

        calendar_client = GoogleCalendarClient(credentials=creds, calendar_id="primary")
        tasks = task_repo.get_all(current_user.id)
        tasks_dict = {task.id: task for task in tasks}
        current_block_ids = {b.id for b in blocks}
        
        def _parse_rfc3339(dt_str: Optional[str]) -> Optional[datetime]:
            if not dt_str:
                return None
            try:
                return datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
            except Exception:
                return None

        def _to_utc_naive(dt: Optional[datetime]) -> Optional[datetime]:
            if dt is None:
                return None
            if dt.tzinfo is None:
                return dt
            return dt.astimezone(timezone.utc).replace(tzinfo=None)

        def _event_private(event: dict) -> dict:
            return ((event.get("extendedProperties") or {}).get("private") or {})

        def _is_managed_event_for_block(event: dict, block_id: str) -> bool:
            priv = _event_private(event)
            return priv.get(PRIVATE_KEY_MANAGED) == "1" and priv.get(PRIVATE_KEY_BLOCK_ID) == block_id

        def _needs_patch(event: dict, *, desired: dict) -> bool:
            # Compare only the fields we own (summary, description, start/end, private keys).
            if (event.get("summary") or "") != (desired.get("summary") or ""):
                return True
            if (event.get("description") or "") != (desired.get("description") or ""):
                return True
            ev_start = (event.get("start") or {}).get("dateTime")
            ev_end = (event.get("end") or {}).get("dateTime")
            d_start = (desired.get("start") or {}).get("dateTime")
            d_end = (desired.get("end") or {}).get("dateTime")
            if (ev_start or "") != (d_start or "") or (ev_end or "") != (d_end or ""):
                return True
            ev_priv = _event_private(event)
            d_priv = ((desired.get("extendedProperties") or {}).get("private") or {})
            for k in (PRIVATE_KEY_TASK_ID, PRIVATE_KEY_BLOCK_ID, PRIVATE_KEY_MANAGED):
                if (ev_priv.get(k) or "") != (d_priv.get(k) or ""):
                    return True
            return False

        events_created = 0
        event_ids: List[str] = []

        schedule_repo = ScheduledBlockRepository(db)

        # Cleanup: delete orphaned qzWhatNext-managed events within the schedule window.
        try:
            starts = [b.start_time for b in blocks if b.start_time]
            ends = [b.end_time for b in blocks if b.end_time]
            if starts and ends:
                from datetime import timedelta

                window_start = min(starts) - timedelta(days=2)
                window_end = max(ends) + timedelta(days=2)

                def _to_rfc3339_z(dt: datetime) -> str:
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                    else:
                        dt = dt.astimezone(timezone.utc)
                    return dt.isoformat().replace("+00:00", "Z")

                for ev in calendar_client.list_events_in_range(
                    time_min_rfc3339=_to_rfc3339_z(window_start),
                    time_max_rfc3339=_to_rfc3339_z(window_end),
                ):
                    priv = ((ev.get("extendedProperties") or {}).get("private") or {})
                    if priv.get(PRIVATE_KEY_MANAGED) != "1":
                        continue
                    ev_block_id = priv.get(PRIVATE_KEY_BLOCK_ID)
                    if not ev_block_id or ev_block_id in current_block_ids:
                        continue
                    ev_id = ev.get("id")
                    if ev_id:
                        calendar_client.delete_event(ev_id)
        except Exception:
            # Best-effort cleanup; never block sync.
            pass

        for block in blocks:
            if block.entity_type != "task":
                continue

            task = tasks_dict.get(block.entity_id)
            if task is None:
                continue

            try:
                event = None
                event_id = block.calendar_event_id

                # 1) Prefer direct lookup by persisted event id
                if event_id:
                    event = calendar_client.get_event(event_id)
                    # If the event was deleted in Google Calendar, treat as missing so we recreate it.
                    if event is None or (isinstance(event, dict) and event.get("status") == "cancelled"):
                        # Event missing (deleted). Clear mapping so we can recreate.
                        schedule_repo.update_calendar_sync_metadata(
                            current_user.id,
                            block.id,
                            calendar_event_id=None,
                            calendar_event_etag=None,
                            calendar_event_updated_at=None,
                        )
                        event_id = None
                        event = None

                # 2) Fallback: find existing event by private block id (legacy / adopted)
                if event is None and not event_id:
                    event = calendar_client.find_event_by_block_id(block.id)
                    if event is not None:
                        # Defensive: only accept if it actually carries our block marker.
                        priv = _event_private(event)
                        if priv.get(PRIVATE_KEY_BLOCK_ID) == block.id:
                            event_id = event.get("id")
                        else:
                            event = None
                            event_id = None

                # 3) Create if missing
                if event is None:
                    created = calendar_client.create_event_from_block(block, task)
                    event_id = created.get("id")
                    events_created += 1
                    if event_id:
                        event_ids.append(event_id)
                    schedule_repo.update_calendar_sync_metadata(
                        current_user.id,
                        block.id,
                        calendar_event_id=event_id,
                        calendar_event_etag=created.get("etag"),
                        calendar_event_updated_at=_to_utc_naive(_parse_rfc3339(created.get("updated"))),
                    )
                    continue

                if not event_id:
                    # Shouldn't happen, but never touch unknown ids.
                    continue

                # 4) Adopt legacy event by adding managed marker (if it looks like ours).
                priv = _event_private(event)
                if priv.get(PRIVATE_KEY_BLOCK_ID) == block.id and priv.get(PRIVATE_KEY_MANAGED) != "1":
                    patch_body = {
                        "extendedProperties": {
                            "private": {
                                PRIVATE_KEY_TASK_ID: block.entity_id,
                                PRIVATE_KEY_BLOCK_ID: block.id,
                                PRIVATE_KEY_MANAGED: "1",
                            }
                        }
                    }
                    event = calendar_client.patch_event(event_id, patch_body)

                # Safety: only update events proven managed for this block.
                if not _is_managed_event_for_block(event, block.id):
                    continue

                # Always persist event id mapping if found.
                if block.calendar_event_id != event_id:
                    schedule_repo.update_calendar_sync_metadata(
                        current_user.id,
                        block.id,
                        calendar_event_id=event_id,
                    )

                event_etag = event.get("etag")
                event_updated_at = _to_utc_naive(_parse_rfc3339(event.get("updated")))

                has_baseline = bool(block.calendar_event_etag or block.calendar_event_updated_at)
                calendar_changed = has_baseline and (
                    (block.calendar_event_etag or "") != (event_etag or "")
                    or (block.calendar_event_updated_at != event_updated_at)
                )

                if not has_baseline:
                    # First time we see this event with no stored calendar version metadata.
                    # Record baseline, but do NOT treat it as a user calendar edit.
                    schedule_repo.update_calendar_sync_metadata(
                        current_user.id,
                        block.id,
                        calendar_event_id=event_id,
                        calendar_event_etag=event_etag,
                        calendar_event_updated_at=event_updated_at,
                    )

                if calendar_changed:
                    # Import calendar time into qzWhatNext and lock if time changed.
                    start_str = (event.get("start") or {}).get("dateTime")
                    end_str = (event.get("end") or {}).get("dateTime")
                    if start_str and end_str:
                        ev_start = _to_utc_naive(_parse_rfc3339(start_str))
                        ev_end = _to_utc_naive(_parse_rfc3339(end_str))
                        if ev_start and ev_end:
                            time_changed = ev_start != block.start_time or ev_end != block.end_time
                            schedule_repo.update_times_and_lock(
                                current_user.id,
                                block.id,
                                start_time=ev_start,
                                end_time=ev_end,
                                lock=time_changed,
                            )
                    # Import title/notes from Calendar to prevent overwriting user edits.
                    ev_title = event.get("summary")
                    ev_notes = event.get("description")
                    if (ev_title is not None and ev_title != task.title) or (ev_notes is not None and ev_notes != task.notes):
                        existing = task_repo.get(current_user.id, task.id)
                        if existing is not None:
                            updated_task = existing.model_copy(
                                update={
                                    "title": ev_title if ev_title is not None else existing.title,
                                    "notes": ev_notes if ev_notes is not None else existing.notes,
                                    "updated_at": datetime.utcnow(),
                                }
                            )
                            task_repo.update(updated_task)
                    schedule_repo.update_calendar_sync_metadata(
                        current_user.id,
                        block.id,
                        calendar_event_id=event_id,
                        calendar_event_etag=event_etag,
                        calendar_event_updated_at=event_updated_at,
                    )
                    continue

                # No calendar-side edits since last sync: push app state if needed.
                desired = {
                    "summary": task.title,
                    "description": task.notes,
                    "start": {"dateTime": block.start_time.isoformat(), "timeZone": "UTC"},
                    "end": {"dateTime": block.end_time.isoformat(), "timeZone": "UTC"},
                    "extendedProperties": {
                        "private": {
                            PRIVATE_KEY_TASK_ID: block.entity_id,
                            PRIVATE_KEY_BLOCK_ID: block.id,
                            PRIVATE_KEY_MANAGED: "1",
                        }
                    },
                }
                if _needs_patch(event, desired=desired):
                    updated = calendar_client.patch_event(event_id, desired)
                    schedule_repo.update_calendar_sync_metadata(
                        current_user.id,
                        block.id,
                        calendar_event_id=event_id,
                        calendar_event_etag=updated.get("etag"),
                        calendar_event_updated_at=_to_utc_naive(_parse_rfc3339(updated.get("updated"))),
                    )

            except Exception as e:
                logger.error(
                    f"Failed to sync calendar event for block {block.id}: {type(e).__name__}: {str(e)}"
                )
                continue

        return SyncResponse(events_created=events_created, event_ids=event_ids)
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to sync calendar: {type(e).__name__}: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Failed to sync calendar: {str(e)}")


@app.post("/schedule/blocks/{block_id}/lock", response_model=ScheduledBlockResponse)
async def lock_scheduled_block(
    block_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Freeze a scheduled block date/time so rebuild won't move it."""
    repo = ScheduledBlockRepository(db)
    updated = repo.set_locked(current_user.id, block_id, True)
    if updated is None:
        raise HTTPException(status_code=404, detail="Scheduled block not found")
    return ScheduledBlockResponse(block=updated)


@app.post("/schedule/blocks/{block_id}/unlock", response_model=ScheduledBlockResponse)
async def unlock_scheduled_block(
    block_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Unfreeze a scheduled block so rebuild may move it again."""
    repo = ScheduledBlockRepository(db)
    updated = repo.set_locked(current_user.id, block_id, False)
    if updated is None:
        raise HTTPException(status_code=404, detail="Scheduled block not found")
    return ScheduledBlockResponse(block=updated)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
