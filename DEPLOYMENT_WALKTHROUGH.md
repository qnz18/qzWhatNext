# Google Cloud Deployment Walkthrough - Step by Step

This guide walks you through deploying qzWhatNext to Google Cloud Run, step-by-step.

## Overview

You'll complete these steps:
1. Set up GCP project and enable APIs
2. Create Google OAuth credentials for user authentication
3. Generate and store JWT secret in Secret Manager
4. Choose database persistence option
5. Build and deploy Docker image
6. Update OAuth redirect URIs
7. Test multi-user authentication

**Estimated time:** 2-3 hours for minimal deployment

---

## Step 1: GCP Project Setup (15-20 minutes)

### 1.1 Create or Select GCP Project

**In Google Cloud Console:**

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Click the project dropdown at the top
3. Click "New Project"
   - Project name: `qzwhatnext` (or your preferred name)
   - Organization: (select if applicable)
   - Location: (select if applicable)
4. Click "Create"
5. Wait for project creation (may take a minute)
6. Select the new project from the dropdown

**Or use gcloud CLI:**
```bash
# Create new project
gcloud projects create qzwhatnext --name="qzWhatNext"

# Set as current project
gcloud config set project qzwhatnext
```

### 1.2 Enable Billing

1. In Google Cloud Console, go to **Billing** (left menu)
2. Link a billing account (Cloud Run requires billing)
3. Confirm billing is enabled for your project

**Note:** Cloud Run has a free tier, but billing must be enabled.

### 1.3 Enable Required APIs

**Using Google Cloud Console:**

1. Go to **APIs & Services** > **Library**
2. Enable these APIs (search and click "Enable"):
   - **Cloud Run API**
   - **Cloud Build API**
   - **Secret Manager API**
   - **Google Identity API** (for OAuth user authentication)
   - **Google Calendar API** (optional, for calendar integration)
   - **Google Sheets API** (optional, for Sheets integration)

**Or use gcloud CLI:**
```bash
# Enable required APIs
gcloud services enable run.googleapis.com
gcloud services enable cloudbuild.googleapis.com
gcloud services enable secretmanager.googleapis.com
gcloud services enable people.googleapis.com  # Google Identity API

# Optional APIs
gcloud services enable calendar-json.googleapis.com
gcloud services enable sheets.googleapis.com
```

### 1.4 Install/Verify gcloud CLI

**Check if gcloud is installed:**
```bash
gcloud --version
```

**If not installed:**
- Download from: https://cloud.google.com/sdk/docs/install
- Or use Homebrew (Mac): `brew install google-cloud-sdk`

**Authenticate:**
```bash
gcloud auth login
gcloud auth application-default login
```

---

## Step 2: Google OAuth Configuration (20-30 minutes)

### 2.1 Configure OAuth Consent Screen

1. Go to **APIs & Services** > **OAuth consent screen**
2. Choose user type:
   - **External** (if others will use it)
   - **Internal** (only for users in your Google Workspace)
3. Fill in required fields:
   - **App name:** `qzWhatNext`
   - **User support email:** Your email
   - **Developer contact:** Your email
4. Click "Save and Continue"
5. **Scopes** (step 2):
   - Click "Add or Remove Scopes"
   - Add: `../auth/userinfo.email`, `../auth/userinfo.profile`
   - Click "Update" then "Save and Continue"
6. **Test users** (step 3, if External):
   - Add your email and any test accounts
   - Click "Save and Continue"
7. **Summary:** Review and go back to dashboard

### 2.2 Create OAuth 2.0 Credentials

1. Go to **APIs & Services** > **Credentials**
2. Click **+ CREATE CREDENTIALS** > **OAuth client ID**
3. Application type: **Web application**
4. Name: `qzWhatNext User Auth`
5. **Authorized JavaScript origins:**
   - `http://localhost:8000` (for local development)
   - *(We'll add production URL later)*
6. **Authorized redirect URIs:**
   - `http://localhost:8000` (for local development)
   - *(We'll add production URL after deployment)*
7. Click **Create**
8. **IMPORTANT:** Copy these values (you won't see them again):
   - **Client ID:** `xxxxx.apps.googleusercontent.com`
   - **Client Secret:** `xxxxx` (save this securely)

**Save the Client ID** - you'll need it for deployment!

---

## Step 3: Generate and Store JWT Secret (10 minutes)

### 3.1 Generate JWT Secret

Generate a secure random key:
```bash
openssl rand -hex 32
```

**Example output:** `a1b2c3d4e5f6...` (64 character hex string)

**Save this value** - you'll need it for the next step.

### 3.2 Store Secret in Secret Manager

**Using gcloud CLI:**
```bash
# Set your project (if not already set)
gcloud config set project qzwhatnext

# Store JWT secret (replace YOUR_JWT_SECRET with the value from step 3.1)
echo -n 54bb5d4d56b4ee67ebc35d75d3ce15fe83cd8b68104d850f1dbabfd2aa140cd8 | gcloud secrets create jwt-secret --data-file=-

# Verify secret was created
gcloud secrets list
```

**Note:** If secret already exists, update it:
```bash
echo -n "YOUR_JWT_SECRET" | gcloud secrets versions add jwt-secret --data-file=-
```

### 3.3 Grant Cloud Run Access to Secret

**Get your project number:**
```bash
gcloud projects describe qzwhatnext --format="value(projectNumber)"
```

**Grant access (replace PROJECT_NUMBER with actual value):**
```bash
gcloud secrets add-iam-policy-binding jwt-secret \
  --member="serviceAccount:729364238212-compute@developer.gserviceaccount.com" \
  --role="roles/secretmanager.secretAccessor"
```

**Alternative:** Grant access to the default Cloud Run service account:
```bash
PROJECT_NUMBER=$(gcloud projects describe qzwhatnext --format="value(projectNumber)")
gcloud secrets add-iam-policy-binding jwt-secret \
  --member="serviceAccount:${PROJECT_NUMBER}-compute@developer.gserviceaccount.com" \
  --role="roles/secretmanager.secretAccessor"
```

---

## Step 4: Database Persistence Decision (5 minutes)

Choose one option:

### Option A: SQLite with Ephemeral Storage (Testing Only) ⚠️

**Pros:** Free, quick to set up
**Cons:** Data resets on each deployment/restart

**When to use:** Testing, development, proof-of-concept

**No action needed** - this is the default. Just note that data won't persist.

### Option B: SQLite with Cloud Storage Volume (Deprecated) ⚠️

Historically, this walkthrough mentioned mounting a Cloud Storage bucket into Cloud Run to persist a SQLite file.

**Status:** Not recommended / not covered. Use Cloud SQL (Option C) for persistence on Cloud Run.

### Option C: Cloud SQL PostgreSQL (Production)

**Pros:** Full scaling, multiple instances, production-ready
**Cons:** Costs ~$10-30/month

**When to use:** Multiple users, production environment

**Setup (covered below):** Create Cloud SQL, store `DATABASE_URL` in Secret Manager, and attach the instance to Cloud Run.

**For persistent storage on Cloud Run, use Option C (Cloud SQL Postgres).**

---

## Step 5: Build and Deploy to Cloud Run (30-45 minutes)

### 5.1 Prepare Deployment Variables

**Set these variables:**
```bash
# Your GCP project ID
export PROJECT_ID=qzwhatnext

# Your Google OAuth Client ID (from Step 2.2)
export GOOGLE_OAUTH_CLIENT_ID=729364238212-s93d4ua1vko5aqn86b2pctb0bnl7i3vj.apps.googleusercontent.com

# Region (us-central1, us-east1, etc.)
export REGION=us-central1

# Service name
export SERVICE_NAME=qzwhatnext
```

### 5.2 Create Cloud SQL PostgreSQL (if using Option C)

```bash
# Enable Cloud SQL Admin API
gcloud services enable sqladmin.googleapis.com --project "$PROJECT_ID"

# Create a Postgres instance (pick a name)
export CLOUDSQL_INSTANCE=qzwhatnext-postgres
gcloud sql instances create "$CLOUDSQL_INSTANCE" \
  --database-version=POSTGRES_15 \
  --region="$REGION" \
  --cpu=1 \
  --memory=3840MiB \
  --storage-size=10GB \
  --project="$PROJECT_ID"

# Create a database + user (pick values)
export DB_NAME=qzwhatnext
export DB_USER=qzwhatnext
export DB_PASSWORD='REPLACE_WITH_STRONG_PASSWORD'

gcloud sql databases create "$DB_NAME" --instance="$CLOUDSQL_INSTANCE" --project="$PROJECT_ID"
gcloud sql users create "$DB_USER" --instance="$CLOUDSQL_INSTANCE" --password="$DB_PASSWORD" --project="$PROJECT_ID"

# Get the instance connection name (needed for Cloud Run)
export INSTANCE_CONNECTION_NAME="$(gcloud sql instances describe "$CLOUDSQL_INSTANCE" --project "$PROJECT_ID" --format='value(connectionName)')"
echo "$INSTANCE_CONNECTION_NAME"
```

### 5.3 Build Docker Image

**From your project directory:**
```bash
# Navigate to project root
cd /path/to/qzWhatNext

# Use Artifact Registry (recommended)
gcloud services enable artifactregistry.googleapis.com --project $PROJECT_ID

# Create a Docker repo in Artifact Registry (one-time)
gcloud artifacts repositories create qzwhatnext \
  --repository-format=docker \
  --location $REGION \
  --description="qzWhatNext container images" \
  --project $PROJECT_ID

# Configure Docker auth for Artifact Registry
gcloud auth configure-docker $REGION-docker.pkg.dev --quiet

# Build + push
docker build -t $REGION-docker.pkg.dev/$PROJECT_ID/qzwhatnext/$SERVICE_NAME .
docker push $REGION-docker.pkg.dev/$PROJECT_ID/qzwhatnext/$SERVICE_NAME
```

**This will:**
- Build your Docker image
- Push it to Artifact Registry
- Take 5-10 minutes (first time)

**Note:** Make sure you're in the project root directory with `Dockerfile`.

### 5.4 Deploy to Cloud Run

**For Option A (Ephemeral Storage - Testing):**
```bash
gcloud run deploy $SERVICE_NAME \
  --image $REGION-docker.pkg.dev/$PROJECT_ID/qzwhatnext/$SERVICE_NAME \
  --platform managed \
  --region $REGION \
  --allow-unauthenticated \
  --set-env-vars "GOOGLE_OAUTH_CLIENT_ID=$GOOGLE_OAUTH_CLIENT_ID,DATABASE_URL=sqlite:///./qzwhatnext.db" \
  --set-secrets "JWT_SECRET_KEY=jwt-secret:latest"
```

### Option C (Cloud SQL Postgres - Persistent Storage)

1) Store `DATABASE_URL` in Secret Manager (recommended: keep DB password out of env vars):

```bash
# Create a secret containing the full DB URL (no newlines)
export DATABASE_URL="postgresql+psycopg://$DB_USER:$DB_PASSWORD@/$DB_NAME?host=/cloudsql/$INSTANCE_CONNECTION_NAME"
printf "%s" "$DATABASE_URL" | gcloud secrets create database-url --data-file=- --project "$PROJECT_ID"

# If the secret already exists, add a new version instead:
# printf "%s" "$DATABASE_URL" | gcloud secrets versions add database-url --data-file=- --project "$PROJECT_ID"
```

2) Grant Cloud Run service account access (Secret Manager + Cloud SQL):

```bash
PROJECT_NUMBER="$(gcloud projects describe "$PROJECT_ID" --format="value(projectNumber)")"
RUN_SA="${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"

gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member="serviceAccount:${RUN_SA}" \
  --role="roles/cloudsql.client"

gcloud secrets add-iam-policy-binding database-url \
  --member="serviceAccount:${RUN_SA}" \
  --role="roles/secretmanager.secretAccessor" \
  --project "$PROJECT_ID"
```

3) Deploy (attach Cloud SQL + source `DATABASE_URL` from Secret Manager):

```bash
gcloud run deploy $SERVICE_NAME \
  --image $REGION-docker.pkg.dev/$PROJECT_ID/qzwhatnext/$SERVICE_NAME \
  --platform managed \
  --region $REGION \
  --allow-unauthenticated \
  --add-cloudsql-instances "$INSTANCE_CONNECTION_NAME" \
  --set-env-vars "GOOGLE_OAUTH_CLIENT_ID=$GOOGLE_OAUTH_CLIENT_ID" \
  --set-secrets "JWT_SECRET_KEY=jwt-secret:latest,DATABASE_URL=database-url:latest" \
  --memory 512Mi \
  --timeout 300
```

**For Option A (Ephemeral Storage - Recommended for quick testing):**
```bash
gcloud run deploy $SERVICE_NAME \
  --image $REGION-docker.pkg.dev/$PROJECT_ID/qzwhatnext/$SERVICE_NAME \
  --platform managed \
  --region $REGION \
  --allow-unauthenticated \
  --set-env-vars "GOOGLE_OAUTH_CLIENT_ID=$GOOGLE_OAUTH_CLIENT_ID,DATABASE_URL=sqlite:///./qzwhatnext.db" \
  --set-secrets "JWT_SECRET_KEY=jwt-secret:latest" \
  --memory 512Mi \
  --timeout 300
```

### 5.5 Get Deployment URL

After deployment completes, you'll see output like:
```
Service [qzwhatnext] revision [qzwhatnext-00001-abc] has been deployed
Service URL: https://qzwhatnext-xxxxx-uc.a.run.app
```

**Copy the Service URL** - you'll need it for the next step!

---

## Step 6: Update OAuth Redirect URIs (10 minutes)

### 6.1 Update Authorized Redirect URIs

1. Go to **APIs & Services** > **Credentials**
2. Click on your OAuth 2.0 Client ID (`qzWhatNext User Auth`)
3. Under **Authorized redirect URIs**, add:
   - Your Cloud Run URL from Step 5.5: `https://qzwhatnext-xxxxx-uc.a.run.app`
4. Click **Save**

**Also update Authorized JavaScript origins** (if needed):
1. Under **Authorized JavaScript origins**, add:
   - `https://qzwhatnext-xxxxx-uc.a.run.app`

### 6.2 Verify OAuth Configuration

**Check your OAuth client:**
- Client ID: ✅ Saved from Step 2.2
- Redirect URIs: ✅ Include both localhost and production URL
- Secret: ✅ Saved securely

---

## Step 7: Test Multi-User Authentication (20-30 minutes)

### 7.1 Access Your Deployed Application

1. Open your Cloud Run URL: `https://qzwhatnext-xxxxx-uc.a.run.app`
2. You should see the qzWhatNext interface

### 7.2 Test Authentication Flow

**Test User 1:**
1. Click "Sign in with Google" (or similar button)
2. Complete Google OAuth flow
3. You should be redirected back and authenticated
4. Create a test task via the UI or API

**Test API with User 1:**
```bash
# Get your JWT token (from browser dev tools, Network tab, or auth response)
export TOKEN_USER1="eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiIxMDU2MDMzNDM0OTA0MjI2OTQwNDciLCJleHAiOjE3Njg4MDE5ODAsImlhdCI6MTc2ODcxNTU4MH0.CK29ubOq-h1qsnURLiSsxJKI6NIvvv07d9kK6my4XNY"
export SERVICE_URL="https://qzwhatnext-729364238212.us-central1.run.app"

# Create a task as User 1
curl -X POST $SERVICE_URL/tasks \
  -H "Authorization: Bearer $TOKEN_USER1" \
  -H "Content-Type: application/json" \
  -d '{"title": "User 1 Task", "category": "work"}'

# List tasks (should only show User 1's tasks)
curl $SERVICE_URL/tasks \
  -H "Authorization: Bearer $TOKEN_USER1"
```

### 7.3 Test User Isolation

**Test User 2 (different Google account):**
1. Sign out (or use incognito/private window)
2. Sign in with a different Google account
3. Create a task as User 2
4. Verify User 2 only sees their own tasks

**API Test:**
```bash
# Get User 2's JWT token
export TOKEN_USER2="user-2-jwt-token-here"

# List User 2's tasks (should be different from User 1)
curl $SERVICE_URL/tasks \
  -H "Authorization: Bearer $TOKEN_USER2"

# Verify User 2 cannot see User 1's tasks
# (should only return User 2's tasks)
```

### 7.4 Test Schedule Building

```bash
# Build schedule for User 1
curl -X POST $SERVICE_URL/schedule \
  -H "Authorization: Bearer $TOKEN_USER1"

# View schedule for User 1
curl $SERVICE_URL/schedule \
  -H "Authorization: Bearer $TOKEN_USER1"

# Verify User 2 has separate schedule
curl -X POST $SERVICE_URL/schedule \
  -H "Authorization: Bearer $TOKEN_USER2"
```

### 7.5 Verify Data Persistence

**Test data persistence:**
1. Create tasks as User 1
2. Wait a few minutes (to ensure container stays running)
3. Refresh and verify tasks still exist
4. Redeploy (to test if data persists):
   ```bash
   gcloud run deploy $SERVICE_NAME \
     --image $REGION-docker.pkg.dev/$PROJECT_ID/qzwhatnext/$SERVICE_NAME \
     --region $REGION
   ```
5. Check if tasks persist after redeployment

**Note:** With ephemeral storage (Option A), data will reset on redeployment. With Cloud Storage volume (Option B), data should persist.

---

## Troubleshooting

### Issue: "Permission denied" on Secret Manager

**Solution:**
```bash
# Verify secret exists
gcloud secrets list

# Check IAM policy
gcloud secrets get-iam-policy jwt-secret

# Re-grant access (use your actual project number)
PROJECT_NUMBER=$(gcloud projects describe $PROJECT_ID --format="value(projectNumber)")
gcloud secrets add-iam-policy-binding jwt-secret \
  --member="serviceAccount:${PROJECT_NUMBER}-compute@developer.gserviceaccount.com" \
  --role="roles/secretmanager.secretAccessor"
```

### Issue: OAuth redirect URI mismatch

**Symptoms:** Error when signing in: "redirect_uri_mismatch"

**Solution:**
1. Verify Cloud Run URL is correct in OAuth credentials
2. Make sure URL doesn't have trailing slash (or does, consistently)
3. Wait a few minutes for OAuth changes to propagate
4. Check both "Authorized redirect URIs" and "Authorized JavaScript origins"

### Issue: Cannot access Cloud Run service

**Symptoms:** 403 Forbidden or connection refused

**Solution:**
```bash
# Verify service is deployed
gcloud run services list --region $REGION

# Check service URL
gcloud run services describe $SERVICE_NAME --region $REGION --format="value(status.url)"

# Verify --allow-unauthenticated flag was used
gcloud run services get-iam-policy $SERVICE_NAME --region $REGION
```

### Issue: JWT token invalid

**Symptoms:** 401 Unauthorized when making API requests

**Solution:**
1. Verify JWT_SECRET_KEY secret exists and is accessible
2. Check service logs:
   ```bash
   gcloud logging read "resource.type=cloud_run_revision AND resource.labels.service_name=$SERVICE_NAME" --limit 50
   ```
3. Verify token is being sent correctly: `Authorization: Bearer <token>`

### Issue: Database errors

**Symptoms:** Database-related errors in logs

**Solution:**
1. Check if database file has write permissions
2. For Cloud Storage volume: Verify mount is configured correctly
3. Check service logs for specific error messages

---

## Next Steps

After successful deployment:

1. **Set up monitoring:** Enable Cloud Logging and Cloud Monitoring
2. **Configure custom domain:** Map a custom domain to your Cloud Run service
3. **Set up CI/CD:** Automate deployments with Cloud Build
4. **Consider Cloud SQL:** Migrate to PostgreSQL for better scalability
5. **Review costs:** Monitor Cloud Run usage and costs

---

## Quick Reference: Deployment Command

**Minimal deployment (copy and customize):**
```bash
export PROJECT_ID=qzwhatnext
export GOOGLE_OAUTH_CLIENT_ID=your-client-id.apps.googleusercontent.com
export REGION=us-central1
export SERVICE_NAME=qzwhatnext

gcloud services enable artifactregistry.googleapis.com --project $PROJECT_ID
gcloud artifacts repositories create qzwhatnext \
  --repository-format=docker \
  --location $REGION \
  --description="qzWhatNext container images" \
  --project $PROJECT_ID
gcloud auth configure-docker $REGION-docker.pkg.dev --quiet
docker build -t $REGION-docker.pkg.dev/$PROJECT_ID/qzwhatnext/$SERVICE_NAME .
docker push $REGION-docker.pkg.dev/$PROJECT_ID/qzwhatnext/$SERVICE_NAME

gcloud run deploy $SERVICE_NAME \
  --image $REGION-docker.pkg.dev/$PROJECT_ID/qzwhatnext/$SERVICE_NAME \
  --platform managed \
  --region $REGION \
  --allow-unauthenticated \
  --set-env-vars "GOOGLE_OAUTH_CLIENT_ID=$GOOGLE_OAUTH_CLIENT_ID,DATABASE_URL=sqlite:///./qzwhatnext.db" \
  --set-secrets "JWT_SECRET_KEY=jwt-secret:latest" \
  --memory 512Mi \
  --timeout 300
```

**After deployment, get your URL:**
```bash
gcloud run services describe $SERVICE_NAME --region $REGION --format="value(status.url)"
```

---

## Summary Checklist

- [ ] GCP project created and billing enabled
- [ ] Required APIs enabled (Cloud Run, Secret Manager, Identity API)
- [ ] OAuth consent screen configured
- [ ] OAuth 2.0 credentials created (Client ID saved)
- [ ] JWT secret generated and stored in Secret Manager
- [ ] Cloud Run service account has Secret Manager access
- [ ] Docker image built and pushed
- [ ] Cloud Run service deployed
- [ ] OAuth redirect URIs updated with production URL
- [ ] Authentication tested with multiple users
- [ ] Data isolation verified
- [ ] Schedule building tested

**Congratulations! Your qzWhatNext instance is now deployed and accessible from anywhere! 🎉**
