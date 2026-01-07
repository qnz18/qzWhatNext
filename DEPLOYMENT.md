# Deployment Guide for qzWhatNext

This guide covers deploying qzWhatNext to Google Cloud Platform.

## Prerequisites

1. Google Cloud account with billing enabled
2. Google Cloud SDK (`gcloud`) installed and configured
3. Python 3.9+ installed locally
4. Google Calendar API and Google Sheets API enabled in your GCP project (optional, for integrations)

## Option 1: Google App Engine

### Setup

1. Create a new GCP project (or use existing):
```bash
gcloud projects create qzwhatnext --name="qzWhatNext"
gcloud config set project qzwhatnext
```

2. Enable App Engine:
```bash
gcloud app create --region=us-central
```

3. Set up environment variables in `app.yaml` or use Secret Manager (optional, for Google Calendar/Sheets):
   - `GOOGLE_CALENDAR_ID` (defaults to "primary")
   - `GOOGLE_CALENDAR_CREDENTIALS_PATH` (path to credentials.json)
   - `GOOGLE_SHEETS_CREDENTIALS_PATH` (path to credentials.json)
   - `DATABASE_URL` (optional, defaults to SQLite)

4. Upload credentials (optional, for Google Calendar/Sheets):
   - Place `credentials.json` in project root (for OAuth2 setup)
   - Note: For production, use Secret Manager instead
   - The same credentials file can be used for both Calendar and Sheets APIs

### Deploy

```bash
gcloud app deploy
```

### Access

```bash
gcloud app browse
```

## Option 2: Google Cloud Run

### Setup

1. Build and push Docker image:
```bash
# Set project
gcloud config set project qzwhatnext

# Build image
gcloud builds submit --tag gcr.io/qzwhatnext/qzwhatnext

# Or use Docker directly
docker build -t gcr.io/qzwhatnext/qzwhatnext .
docker push gcr.io/qzwhatnext/qzwhatnext
```

2. Deploy to Cloud Run:
```bash
gcloud run deploy qzwhatnext \
  --image gcr.io/qzwhatnext/qzwhatnext \
  --platform managed \
  --region us-central1 \
  --allow-unauthenticated \
  --set-env-vars GOOGLE_CALENDAR_ID=primary,DATABASE_URL=sqlite:///./qzwhatnext.db
```

**Note:** For production, consider using Cloud SQL (PostgreSQL) instead of SQLite for better scalability and reliability. Update `DATABASE_URL` accordingly.

### Access

Cloud Run will provide a URL after deployment.

## Environment Variables

Set these in your deployment:

- `GOOGLE_CALENDAR_CREDENTIALS_PATH`: Path to OAuth2 credentials for Calendar API (optional, use Secret Manager for production)
- `GOOGLE_SHEETS_CREDENTIALS_PATH`: Path to OAuth2 credentials for Sheets API (optional, use Secret Manager for production)
- `GOOGLE_CALENDAR_ID`: Calendar ID (defaults to "primary")
- `DATABASE_URL`: Database connection string (defaults to `sqlite:///./qzwhatnext.db`)
- `DEBUG`: Set to "False" in production

## Google Calendar/Sheets OAuth2 Setup

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Enable Google Calendar API and Google Sheets API
3. Create OAuth2 credentials (Web app type for production)
4. Download as `credentials.json`
5. For first run, the app will open a browser for OAuth2 authorization
6. Tokens will be saved to `token.json` (Calendar) and `sheets_token.json` (Sheets) - add to .gitignore

## Security Notes

- Never commit `credentials.json` or `token.json` to version control
- Use Google Secret Manager for production credentials
- Restrict API access to necessary scopes only
- Use least-privilege IAM roles

## Troubleshooting

### Database Issues
- SQLite database file (`qzwhatnext.db`) needs write permissions
- For production, consider migrating to PostgreSQL (Cloud SQL)
- Database is automatically created on first run

### OAuth2 Issues
- Ensure credentials.json is in the correct location
- Check that Calendar API and Sheets API are enabled
- Verify OAuth2 consent screen is configured
- For production, use Secret Manager for credentials

### Import Failures
- Verify Google Calendar/Sheets credentials are valid (if using integrations)
- For Google Sheets: Verify spreadsheet ID and sheet is accessible
- Check network connectivity
- Review API rate limits

### Scheduling Issues
- Check that tasks exist in database (use `GET /tasks` endpoint)
- Verify task data is valid
- Review scheduler logs

