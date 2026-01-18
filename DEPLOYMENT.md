# Deployment Guide for qzWhatNext

This guide covers deploying qzWhatNext to Google Cloud Platform.

## Prerequisites

1. Google Cloud account with billing enabled
2. Google Cloud SDK (`gcloud`) installed and configured
3. Python 3.9+ installed locally
4. **Multi-user authentication setup (required):**
   - Google OAuth credentials for user authentication (different from Calendar/Sheets OAuth)
   - Enable Google+ API or Google Identity API in your GCP project
   - Create OAuth2 credentials (Web app type) for user authentication
5. Google Calendar API and Google Sheets API enabled in your GCP project (optional, for integrations)

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

3. Set up environment variables in `app.yaml` or use Secret Manager:
   - **Required for multi-user authentication:**
     - `GOOGLE_OAUTH_CLIENT_ID` - OAuth client ID for user authentication (public, can be in env vars)
     - `JWT_SECRET_KEY` - Secure random key for JWT signing (use Secret Manager in production)
   - **Optional JWT configuration:**
     - `JWT_ALGORITHM` (defaults to "HS256")
     - `JWT_EXPIRATION_HOURS` (defaults to "24")
   - **Optional for Google Calendar/Sheets:**
     - `GOOGLE_CALENDAR_ID` (defaults to "primary")
     - `GOOGLE_CALENDAR_CREDENTIALS_PATH` (path to credentials.json)
     - `GOOGLE_SHEETS_CREDENTIALS_PATH` (path to credentials.json)
   - `DATABASE_URL` (optional, defaults to SQLite)
   - `OPENAI_API_KEY` - For AI category inference (optional, use Secret Manager)

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
# Deploy with required multi-user authentication environment variables
gcloud run deploy qzwhatnext \
  --image gcr.io/qzwhatnext/qzwhatnext \
  --platform managed \
  --region us-central1 \
  --allow-unauthenticated \
  --set-env-vars GOOGLE_OAUTH_CLIENT_ID=your-client-id.apps.googleusercontent.com,DATABASE_URL=sqlite:///./qzwhatnext.db \
  --set-secrets JWT_SECRET_KEY=jwt-secret:latest
```

**Note:** Replace `your-client-id.apps.googleusercontent.com` with your actual Google OAuth client ID, and ensure `jwt-secret` exists in Secret Manager (see Secret Management section below).

**Note:** SQLite database files are stored in ephemeral storage by default. For production:
- **Option 1 (Minimal):** Mount Cloud Storage bucket as volume for SQLite persistence (single instance only)
- **Option 2 (Production):** Migrate to Cloud SQL (PostgreSQL) for better scalability and multi-instance support. Update `DATABASE_URL` accordingly.

### Access

Cloud Run will provide a URL after deployment.

## Multi-User Authentication Setup

qzWhatNext uses Google OAuth for user authentication. All API endpoints require Bearer token authentication.

### 1. Google OAuth Configuration

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Enable Google+ API or Google Identity API (for user info)
3. Create OAuth2 credentials:
   - Type: Web application
   - **Critical:** Add authorized redirect URIs:
     - `http://localhost:8000` (for local development)
     - `https://your-cloud-run-url.run.app` (for production, add after deployment)
4. Copy the Client ID and Client Secret

### 2. Secret Management

**Store secrets in Google Secret Manager (recommended for production):**

```bash
# Store JWT secret key
echo -n "your-secure-random-jwt-secret-key" | gcloud secrets create jwt-secret --data-file=-

# Store OpenAI API key (optional)
echo -n "your-openai-api-key" | gcloud secrets create openai-api-key --data-file=-

# Grant Cloud Run service account access to secrets
gcloud secrets add-iam-policy-binding jwt-secret \
  --member="serviceAccount:YOUR-SERVICE-ACCOUNT@PROJECT-ID.iam.gserviceaccount.com" \
  --role="roles/secretmanager.secretAccessor"
```

**Generate a secure JWT secret:**
```bash
# Generate a secure random key
openssl rand -hex 32
```

### 3. Environment Variables

Set these in your deployment:

**Required:**
- `GOOGLE_OAUTH_CLIENT_ID`: OAuth client ID for user authentication (public, exposed to frontend)
- `JWT_SECRET_KEY`: Secure JWT signing key (use Secret Manager in production)

**Optional:**
- `GOOGLE_OAUTH_CLIENT_SECRET`: OAuth client secret (for future use, store in Secret Manager)
- `JWT_ALGORITHM`: JWT algorithm (defaults to "HS256")
- `JWT_EXPIRATION_HOURS`: Token expiration in hours (defaults to "24")
- `GOOGLE_CALENDAR_CREDENTIALS_PATH`: Path to OAuth2 credentials for Calendar API (optional, separate from user OAuth)
- `GOOGLE_SHEETS_CREDENTIALS_PATH`: Path to OAuth2 credentials for Sheets API (optional, separate from user OAuth)
- `GOOGLE_CALENDAR_ID`: Calendar ID (defaults to "primary")
- `OPENAI_API_KEY`: OpenAI API key for AI category inference (optional, use Secret Manager)
- `DATABASE_URL`: Database connection string (defaults to `sqlite:///./qzwhatnext.db`)
- `DEBUG`: Set to "False" in production

**Note:** User authentication OAuth credentials are different from Calendar/Sheets API OAuth credentials. You need separate OAuth2 credentials for user authentication.

## Google Calendar/Sheets OAuth2 Setup (Optional)

**Note:** This is separate from user authentication OAuth. These credentials are for Calendar/Sheets API integration only.

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Enable Google Calendar API and Google Sheets API
3. Create OAuth2 credentials (Web app type for production)
4. Download as `credentials.json`
5. For first run, the app will open a browser for OAuth2 authorization
6. Tokens will be saved to `token.json` (Calendar) and `sheets_token.json` (Sheets) - already in .gitignore

## Security Notes

- Never commit `credentials.json`, `token.json`, or API keys to version control
- Use Google Secret Manager for production credentials (Calendar, Sheets, OpenAI)
- Restrict API access to necessary scopes only
- Use least-privilege IAM roles
- Never log API keys or sensitive data

## Troubleshooting

### Database Issues
- SQLite database file (`qzwhatnext.db`) needs write permissions
- For production, consider migrating to PostgreSQL (Cloud SQL)
- Database is automatically created on first run

### Authentication Issues

**User Authentication (OAuth):**
- Verify `GOOGLE_OAUTH_CLIENT_ID` is set correctly
- Check that authorized redirect URIs include your deployed URL
- Ensure JWT secret key is configured (check Secret Manager access)
- Verify Google+ API or Google Identity API is enabled

**Calendar/Sheets OAuth2:**
- Ensure credentials.json is in the correct location (for Calendar/Sheets only)
- Check that Calendar API and Sheets API are enabled
- Verify OAuth2 consent screen is configured
- For production, use Secret Manager for credentials

### Import Failures
- Verify Google Calendar/Sheets credentials are valid (if using integrations)
- For Google Sheets: Verify spreadsheet ID and sheet is accessible
- Check network connectivity
- Review API rate limits

### Multi-User Data Isolation
- Verify users can only see their own tasks (test with different Google accounts)
- Check that `user_id` is correctly set on all tasks
- Ensure Bearer token is included in API requests (Authorization header)

### Scheduling Issues
- Check that tasks exist in database for the authenticated user (use `GET /tasks` endpoint with Bearer token)
- Verify task data is valid
- Review scheduler logs
- Ensure schedule is user-scoped (each user has their own schedule)

