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
export PROJECT_ID=qzwhatnext
export REGION=us-central1
gcloud config set project $PROJECT_ID

# Enable Artifact Registry (recommended)
gcloud services enable artifactregistry.googleapis.com

# Create a Docker repo in Artifact Registry (one-time)
gcloud artifacts repositories create qzwhatnext \
  --repository-format=docker \
  --location $REGION \
  --description="qzWhatNext container images" \
  --project $PROJECT_ID

# Configure Docker auth for Artifact Registry
gcloud auth configure-docker $REGION-docker.pkg.dev --quiet

# Build + push image
docker build -t $REGION-docker.pkg.dev/$PROJECT_ID/qzwhatnext/qzwhatnext .
docker push $REGION-docker.pkg.dev/$PROJECT_ID/qzwhatnext/qzwhatnext
```

2. Deploy to Cloud Run:
```bash
# Deploy with required multi-user authentication environment variables
gcloud run deploy qzwhatnext \
  --image $REGION-docker.pkg.dev/$PROJECT_ID/qzwhatnext/qzwhatnext \
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
- `GOOGLE_OAUTH_CLIENT_SECRET`: Required for per-user Google Calendar connect (store in Secret Manager)
- `TOKEN_ENCRYPTION_KEY`: Fernet key used to encrypt stored OAuth refresh tokens at rest (store in Secret Manager)

**Optional:**
- `JWT_ALGORITHM`: JWT algorithm (defaults to "HS256")
- `JWT_EXPIRATION_HOURS`: Token expiration in hours (defaults to "24")
- `GOOGLE_SHEETS_CREDENTIALS_PATH`: Path to OAuth2 credentials for Sheets API (legacy/local-dev flow)
- `GOOGLE_CALENDAR_ID`: Calendar ID (defaults to "primary")
- `OPENAI_API_KEY`: OpenAI API key for AI category inference (optional, use Secret Manager)
- `DATABASE_URL`: Database connection string (defaults to `sqlite:///./qzwhatnext.db`)
- `DEBUG`: Set to "False" in production

**Note:** Google Calendar sync uses a **per-user web OAuth flow** and stores refresh tokens encrypted in the DB. It does **not** use `credentials.json` / `token.json` in production.

## Google Calendar OAuth Setup (Optional)

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Enable Google Calendar API
3. Ensure your OAuth consent screen is configured
4. In your OAuth client (Web application):
   - Add your app origin to **Authorized JavaScript origins** (e.g., `http://localhost:8000`, `https://YOUR_DOMAIN`)
   - Add an **Authorized redirect URI** for the manual reconnect flow:
   - `https://YOUR_DOMAIN/auth/google/calendar/callback`
5. Set these secrets in your deployment:
   - `GOOGLE_OAUTH_CLIENT_SECRET`
   - `TOKEN_ENCRYPTION_KEY`
6. With these configured, the initial Google sign-in can grant Calendar access (one-time consent). If a user revokes access or tokens expire, the UI may prompt to reconnect.

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
- For Google Calendar sync: verify redirect URI is correct and secrets are set
- For Google Sheets import (legacy/local-dev flow): ensure `credentials.json` is available and Sheets API is enabled
- Verify OAuth2 consent screen is configured
- For production, use Secret Manager for secrets

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

