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

## 2. Configure

Create a `.env` file in the project root:

```bash
TODOIST_API_TOKEN=your_todoist_token_here
GOOGLE_CALENDAR_CREDENTIALS_PATH=credentials.json
GOOGLE_CALENDAR_ID=primary
```

Get your Todoist API token from: https://todoist.com/app/settings/integrations

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

1. Click "Import from Todoist" to fetch your tasks
2. Click "Build Schedule" to create a schedule
3. Click "View Schedule" to see what's scheduled
4. Click "Sync to Google Calendar" to write events (first time will open browser for OAuth2)

## Next Steps

- See `TESTING.md` for detailed testing instructions
- See `DEPLOYMENT.md` for Google Cloud deployment
- See `README.md` for full documentation

