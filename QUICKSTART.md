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

## 2. Configure (Optional - for Google Calendar/Sheets and OpenAI)

Create a `.env` file in the project root:

```bash
GOOGLE_CALENDAR_CREDENTIALS_PATH=credentials.json
GOOGLE_CALENDAR_ID=primary
GOOGLE_SHEETS_CREDENTIALS_PATH=credentials.json
OPENAI_API_KEY=sk-your-api-key-here
```

**Note:** 
- Google Calendar/Sheets setup is optional. You can use the scheduling features and REST API without Google integration.
- OpenAI API key is optional. If not set, category inference will not be available and tasks created via `/tasks/add_smart` will use `UNKNOWN` category. The database (SQLite) will be created automatically.

## 3. Google Calendar/Sheets Setup (Optional)

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project or select existing
3. Enable Google Calendar API and Google Sheets API
4. Create OAuth2 credentials:
   - Choose "Web app" (works for both local and production)
   - **IMPORTANT**: Add `http://localhost:8080/` to "Authorized redirect URIs" (for local development)
   - The exact URI must be: `http://localhost:8080/` (with the trailing slash)
5. Download as `credentials.json` to project root

**Note**: The current implementation uses `InstalledAppFlow` with a fixed port (8080) for OAuth. Make sure `http://localhost:8080/` is exactly in your authorized redirect URIs in Google Cloud Console. If you get a "redirect_uri_mismatch" error, verify this URI is added correctly.

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
  - Requires OAuth2 setup (first time will open browser for authorization)
- **Build schedule**:
  - `POST /schedule` - Create a schedule from tasks in database
  - `GET /schedule` - View the current schedule
- **Sync to Google Calendar**:
  - `POST /sync-calendar` - Write scheduled events to Google Calendar
  - Requires OAuth2 setup (first time will open browser for authorization)

**Note:** 
- Tasks are persisted in SQLite database (`qzwhatnext.db`)
- Database is automatically created on first run
- All data persists across server restarts

## Next Steps

- See `TESTING.md` for detailed testing instructions
- See `DEPLOYMENT.md` for Google Cloud deployment
- See `README.md` for full documentation

