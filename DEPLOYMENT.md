# Deployment Guide for qzWhatNext

This guide covers deploying qzWhatNext to Google Cloud Platform.

## Prerequisites

1. Google Cloud account with billing enabled
2. Google Cloud SDK (`gcloud`) installed and configured
3. Python 3.9+ installed locally
4. Todoist API token
5. Google Calendar API enabled in your GCP project

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

3. Set up environment variables in `app.yaml` or use Secret Manager (optional, for Google Calendar):
   - `GOOGLE_CALENDAR_ID` (defaults to "primary")

4. Upload credentials:
   - Place `credentials.json` in project root (for OAuth2 setup)
   - Note: For production, use Secret Manager instead

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
  --set-env-vars GOOGLE_CALENDAR_ID=primary
```

### Access

Cloud Run will provide a URL after deployment.

## Environment Variables

Set these in your deployment:

   - `GOOGLE_CALENDAR_CREDENTIALS_PATH`: Path to OAuth2 credentials (optional)
- `GOOGLE_CALENDAR_CREDENTIALS_PATH`: Path to OAuth2 credentials (or use Secret Manager)
- `GOOGLE_CALENDAR_ID`: Calendar ID (defaults to "primary")
- `DEBUG`: Set to "False" in production

## Google Calendar OAuth2 Setup

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Enable Google Calendar API
3. Create OAuth2 credentials (Desktop app type)
4. Download as `credentials.json`
5. For first run, the app will open a browser for OAuth2 authorization
6. Token will be saved to `token.json` (add to .gitignore)

## Security Notes

- Never commit `credentials.json` or `token.json` to version control
- Use Google Secret Manager for production credentials
- Restrict API access to necessary scopes only
- Use least-privilege IAM roles

## Troubleshooting

### OAuth2 Issues
- Ensure credentials.json is in the correct location
- Check that Calendar API is enabled
- Verify OAuth2 consent screen is configured

### Import Failures
- Verify Google Calendar credentials are valid (if using calendar sync)
- Check network connectivity
- Review API rate limits

### Scheduling Issues
- Check that tasks were imported successfully
- Verify task data is valid
- Review scheduler logs

