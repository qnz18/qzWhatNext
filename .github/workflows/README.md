# GitHub Actions Workflows

This directory contains GitHub Actions workflows for automated deployment.

## Setup Required

Before using automated deployment, you need to configure GitHub Secrets:

### Required GitHub Secrets

1. **GCP_PROJECT_ID** - Your Google Cloud Project ID (e.g., `qzwhatnext`)
2. **GCP_SA_KEY** - Service Account JSON key for deployment authentication
3. **GOOGLE_OAUTH_CLIENT_ID** - Your Google OAuth Client ID (e.g., `xxx.apps.googleusercontent.com`)

### How to Set Up Secrets

1. Go to your GitHub repository
2. Navigate to **Settings** > **Secrets and variables** > **Actions**
3. Click **New repository secret**
4. Add each secret:

#### GCP_PROJECT_ID
- **Name:** `GCP_PROJECT_ID`
- **Value:** Your GCP project ID (e.g., `qzwhatnext`)

#### GCP_SA_KEY (Service Account Key)

**Create a service account for GitHub Actions:**

```bash
# Create service account
gcloud iam service-accounts create github-actions \
  --display-name="GitHub Actions Deployment"

# Grant necessary permissions
gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:github-actions@$PROJECT_ID.iam.gserviceaccount.com" \
  --role="roles/run.admin"

gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:github-actions@$PROJECT_ID.iam.gserviceaccount.com" \
  --role="roles/iam.serviceAccountUser"

gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:github-actions@$PROJECT_ID.iam.gserviceaccount.com" \
  --role="roles/storage.admin"

gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:github-actions@$PROJECT_ID.iam.gserviceaccount.com" \
  --role="roles/secretmanager.secretAccessor"

# Create and download key
gcloud iam service-accounts keys create gcp-sa-key.json \
  --iam-account=github-actions@$PROJECT_ID.iam.gserviceaccount.com
```

**Copy the contents of `gcp-sa-key.json` and add as GitHub secret:**
- **Name:** `GCP_SA_KEY`
- **Value:** Contents of `gcp-sa-key.json` (entire JSON)

**⚠️ Important:** Delete `gcp-sa-key.json` file after adding to GitHub (don't commit it!)

```bash
rm gcp-sa-key.json
```

#### GOOGLE_OAUTH_CLIENT_ID
- **Name:** `GOOGLE_OAUTH_CLIENT_ID`
- **Value:** Your Google OAuth Client ID (from Google Cloud Console > APIs & Services > Credentials)

### OpenAI inference (Secret Manager, not a GitHub secret)

The workflow maps **`OPENAI_API_KEY`** from Google Secret Manager secret **`openai-api-key:latest`** on Cloud Run (see `deploy.yml` `--set-secrets`). You do **not** add the raw API key to GitHub Secrets.

1. Create the secret in GCP (key from [OpenAI API keys](https://platform.openai.com/api-keys)):
   `printf '%s' 'sk-...' | gcloud secrets create openai-api-key --data-file=-`  
   (or `gcloud secrets versions add openai-api-key --data-file=-` if it already exists).
2. Grant the **Cloud Run runtime** service account **Secret Manager Secret Accessor** on that secret (same pattern as `jwt-secret` below). If deploy fails with permission errors on the new secret, verify this binding.

OpenAI inference is optional: if the secret is missing or empty, the app degrades gracefully (see logs for `OPENAI_API_KEY not found`).

## How It Works

The workflow automatically:
1. Triggers on push to `main` branch (or manual trigger)
2. Authenticates to Google Cloud using service account key
3. Builds Docker image using Cloud Build
4. Deploys to Cloud Run with environment variables and secrets
5. Outputs the service URL

## Manual Deployment Trigger

You can also trigger deployment manually:
1. Go to **Actions** tab in GitHub
2. Select **Deploy to Google Cloud Run**
3. Click **Run workflow**

## Troubleshooting

### Permission Errors

If you see permission errors:
- Verify service account has required roles
- Check that `GCP_SA_KEY` secret contains valid JSON
- Ensure service account email matches the one in the key

### Secret Manager Access

Ensure the Cloud Run **runtime** service account (not the GitHub Actions deploy account) can read each secret referenced in `--set-secrets`, including **`openai-api-key`**.

```bash
PROJECT_NUMBER=$(gcloud projects describe $PROJECT_ID --format="value(projectNumber)")
RUNTIME_SA="${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"

for SECRET in jwt-secret openai-api-key; do
  gcloud secrets add-iam-policy-binding "$SECRET" \
    --member="serviceAccount:${RUNTIME_SA}" \
    --role="roles/secretmanager.secretAccessor" \
    --project="$PROJECT_ID" || true
done
```

Use your revision’s **Service account** from Cloud Run if you use a custom runtime SA (replace `RUNTIME_SA`).

### OAuth Redirect URIs

After first deployment, update OAuth redirect URIs in Google Cloud Console to include the Cloud Run URL.
