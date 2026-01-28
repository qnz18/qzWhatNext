# Quick Start Guide

Get qzWhatNext running in 5 minutes.

## 1. Setup

```bash
# Create virtual environment
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

## 2. Configure (Optional - for Google Calendar, Google Sheets, and OpenAI)

Create a `.env` file in the project root (examples):

```bash
# Required for Google Sign-in (multi-user auth)
GOOGLE_OAUTH_CLIENT_ID=your-client-id.apps.googleusercontent.com
JWT_SECRET_KEY=change-me-in-production

# Required for Google Calendar sync (per-user OAuth token storage)
GOOGLE_OAUTH_CLIENT_SECRET=your-client-secret
TOKEN_ENCRYPTION_KEY=your-fernet-key

# Optional
GOOGLE_CALENDAR_ID=primary
GOOGLE_SHEETS_CREDENTIALS_PATH=credentials.json
OPENAI_API_KEY=sk-your-api-key-here
```

**Note:** 
- Google Calendar/Sheets setup is optional. You can use the scheduling features and REST API without Google integration.
- OpenAI API key is optional. If not set, category inference will not be available and tasks created via `/tasks/add_smart` will use `UNKNOWN` category. The database (SQLite) will be created automatically.

## 3. Google Calendar Setup (Optional)

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project or select existing
3. Enable Google Calendar API
4. Create OAuth2 credentials:
   - Choose "Web application"
   - Add these **Authorized redirect URIs**:
     - `http://localhost:8000/auth/google/calendar/callback`
     - (For production) `https://YOUR_DOMAIN/auth/google/calendar/callback`
5. Copy the Client ID + Client Secret into `.env` as `GOOGLE_OAUTH_CLIENT_ID` / `GOOGLE_OAUTH_CLIENT_SECRET`
6. Generate a Fernet key for `TOKEN_ENCRYPTION_KEY` (this encrypts refresh tokens at rest)

## 4. Run

```bash
python run.py
# Or: uvicorn qzwhatnext.api.app:app --reload
```

Visit `http://localhost:8000` in your browser.

## 5. First Use

**Current Implementation:**
- **Create tasks** via REST API (see API docs at `/docs`)
  - `POST /tasks` - Create a new task
  - `POST /tasks/add_smart` - Create a task with auto-generated title and AI category inference (requires `OPENAI_API_KEY` for inference)
  - `GET /tasks` - List all tasks
  - `GET /tasks/{task_id}` - Get a specific task
  - `PUT /tasks/{task_id}` - Update a task
  - `DELETE /tasks/{task_id}` - Delete a task
- **Import tasks** from Google Sheets:
  - `POST /import/sheets` - Import tasks from a Google Sheet
  - Note: current Sheets integration is optimized for local dev and uses server-local OAuth
- **Build schedule**:
  - `POST /schedule` - Create a schedule from tasks in database
  - `GET /schedule` - View the current schedule
- **Sync to Google Calendar**:
  - `POST /sync-calendar` - Write scheduled events to Google Calendar
  - If `GOOGLE_OAUTH_CLIENT_SECRET` + `TOKEN_ENCRYPTION_KEY` are configured, the initial Google sign-in will also grant Calendar access (one-time consent).
  - Otherwise, the UI will prompt you to connect Google Calendar the first time you sync.

**Note:** 
- Tasks are persisted in SQLite database (`qzwhatnext.db`)
- Database is automatically created on first run
- All data persists across server restarts

## Next Steps

- See `TESTING.md` for detailed testing instructions
- See `DEPLOYMENT.md` for Google Cloud deployment
- See `README.md` for full documentation

