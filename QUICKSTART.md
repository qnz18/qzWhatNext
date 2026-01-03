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

## 2. Configure (Optional - for Google Calendar sync)

Create a `.env` file in the project root:

```bash
GOOGLE_CALENDAR_CREDENTIALS_PATH=credentials.json
GOOGLE_CALENDAR_ID=primary
```

**Note:** Google Calendar setup is optional. You can use the scheduling features without calendar sync.

## 3. Google Calendar Setup

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a new project or select existing
3. Enable Google Calendar API
4. Create OAuth2 credentials:
   - Choose "Web app" (works for both local and production)
   - Add `http://localhost` to "Authorized redirect URIs" (for local development)
5. Download as `credentials.json` to project root

**Note**: The current implementation uses `InstalledAppFlow` which works with both Desktop and Web app credentials. For Web app credentials, make sure `http://localhost` (or `http://localhost:*`) is in your authorized redirect URIs in Google Cloud Console.

## 4. Run

```bash
python run.py
# Or: uvicorn qzwhatnext.api.app:app --reload
```

Visit `http://localhost:8000` in your browser.

## 5. First Use

**Current Implementation:**
- Tasks must be added programmatically (no UI for task creation yet)
- Use the API endpoints to create tasks (see API docs at `/docs`)
- Click "Build Schedule" to create a schedule from tasks in memory
- Click "View Schedule" to see what's scheduled
- Click "Sync to Google Calendar" to write events (first time will open browser for OAuth2)

**Note:** 
- Tasks are stored in-memory (lost on server restart)
- Google Sheets import and REST API for task CRUD are planned but not yet implemented
- See canonical documents for planned features

## Next Steps

- See `TESTING.md` for detailed testing instructions
- See `DEPLOYMENT.md` for Google Cloud deployment
- See `README.md` for full documentation

