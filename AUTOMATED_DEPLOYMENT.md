# Automated Deployment Guide

This guide covers setting up automated deployment for qzWhatNext using GitHub Actions.

## Overview

Automated deployment allows you to deploy qzWhatNext to Google Cloud Run automatically when you push code to the `main` branch. No more manual deployment steps!

## Benefits

✅ **Automatic deployment** on every push to `main`  
✅ **Consistent deployments** - same process every time  
✅ **Faster iteration** - no manual deployment commands  
✅ **Deployment history** - see all deployments in GitHub Actions  

## Quick Start

1. **Set up GitHub Secrets** (one-time setup)
2. **Push to `main` branch** - deployment happens automatically!

## Option 1: GitHub Actions (Recommended)

GitHub Actions is integrated with GitHub and works well for this setup.

### Setup Steps

#### Step 1: Create Service Account for GitHub Actions

```bash
# Set your project ID
export PROJECT_ID=qzwhatnext

# Create service account
gcloud iam service-accounts create github-actions \
  --display-name="GitHub Actions Deployment" \
  --project=$PROJECT_ID

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
  --iam-account=github-actions@$PROJECT_ID.iam.gserviceaccount.com \
  --project=$PROJECT_ID

# Display key (you'll copy this to GitHub Secrets)
cat gcp-sa-key.json

# Clean up local key file (important!)
rm gcp-sa-key.json
```

#### Step 2: Add GitHub Secrets

1. Go to your GitHub repository
2. Navigate to **Settings** > **Secrets and variables** > **Actions**
3. Click **New repository secret**
4. Add these secrets:

**GCP_PROJECT_ID:**
- Name: `GCP_PROJECT_ID`
- Value: Your GCP project ID (e.g., `qzwhatnext`)

**GCP_SA_KEY:**
- Name: `GCP_SA_KEY`
- Value: Contents of `gcp-sa-key.json` (the entire JSON from Step 1)

**GOOGLE_OAUTH_CLIENT_ID:**
- Name: `GOOGLE_OAUTH_CLIENT_ID`
- Value: Your Google OAuth Client ID (from Google Cloud Console)

#### Step 3: Ensure Workflow File Exists

The workflow file should already be in `.github/workflows/deploy.yml`. If not, see the file for the workflow configuration.

#### Step 4: First Deployment

After pushing secrets, push to `main` branch:

```bash
git push origin main
```

Deployment will trigger automatically! Check the **Actions** tab in GitHub to see progress.

### How It Works

When you push to `main`:
1. GitHub Actions workflow triggers
2. Authenticates to GCP using service account key
3. Builds Docker image using Cloud Build
4. Deploys to Cloud Run
5. Service URL is displayed in workflow output

### Manual Trigger

You can also trigger deployment manually:
1. Go to **Actions** tab
2. Select **Deploy to Google Cloud Run**
3. Click **Run workflow**

## Option 2: Google Cloud Build (Alternative)

If you prefer Google Cloud Build, you can set up Cloud Build triggers.

### Setup Cloud Build Trigger

```bash
# Create build configuration file
cat > cloudbuild.yaml <<EOF
steps:
  # Build Docker image
  - name: 'gcr.io/cloud-builders/docker'
    args: ['build', '-t', 'gcr.io/$PROJECT_ID/qzwhatnext', '.']
  
  # Push to Container Registry
  - name: 'gcr.io/cloud-builders/docker'
    args: ['push', 'gcr.io/$PROJECT_ID/qzwhatnext']
  
  # Deploy to Cloud Run
  - name: 'gcr.io/google.com/cloudsdktool/cloud-sdk'
    entrypoint: gcloud
    args:
      - 'run'
      - 'deploy'
      - 'qzwhatnext'
      - '--image=gcr.io/$PROJECT_ID/qzwhatnext'
      - '--platform=managed'
      - '--region=us-central1'
      - '--allow-unauthenticated'
      - '--set-env-vars=GOOGLE_OAUTH_CLIENT_ID=${_GOOGLE_OAUTH_CLIENT_ID},DATABASE_URL=sqlite:///./qzwhatnext.db'
      - '--set-secrets=JWT_SECRET_KEY=jwt-secret:latest'
      - '--memory=512Mi'
      - '--timeout=300'

images:
  - 'gcr.io/$PROJECT_ID/qzwhatnext'

substitutions:
  _GOOGLE_OAUTH_CLIENT_ID: 'your-client-id.apps.googleusercontent.com'
EOF

# Create trigger
gcloud builds triggers create github \
  --repo-name=qzWhatNext \
  --repo-owner=YOUR_GITHUB_USERNAME \
  --branch-pattern="^main$" \
  --build-config=cloudbuild.yaml \
  --project=$PROJECT_ID
```

## Option 3: Simple Deploy Script (Local Automation)

For local automation without CI/CD:

```bash
#!/bin/bash
# deploy.sh - Simple deployment script

set -e

PROJECT_ID=${PROJECT_ID:-qzwhatnext}
SERVICE_NAME=${SERVICE_NAME:-qzwhatnext}
REGION=${REGION:-us-central1}
GOOGLE_OAUTH_CLIENT_ID=${GOOGLE_OAUTH_CLIENT_ID:-}

if [ -z "$GOOGLE_OAUTH_CLIENT_ID" ]; then
  echo "Error: GOOGLE_OAUTH_CLIENT_ID not set"
  exit 1
fi

echo "Building Docker image..."
gcloud builds submit --tag gcr.io/$PROJECT_ID/$SERVICE_NAME

echo "Deploying to Cloud Run..."
gcloud run deploy $SERVICE_NAME \
  --image gcr.io/$PROJECT_ID/$SERVICE_NAME \
  --platform managed \
  --region $REGION \
  --allow-unauthenticated \
  --set-env-vars "GOOGLE_OAUTH_CLIENT_ID=$GOOGLE_OAUTH_CLIENT_ID,DATABASE_URL=sqlite:///./qzwhatnext.db" \
  --set-secrets "JWT_SECRET_KEY=jwt-secret:latest" \
  --memory 512Mi \
  --timeout 300

echo "✅ Deployment complete!"
gcloud run services describe $SERVICE_NAME --region $REGION --format="value(status.url)"
```

**Usage:**
```bash
chmod +x deploy.sh
export GOOGLE_OAUTH_CLIENT_ID=your-client-id.apps.googleusercontent.com
./deploy.sh
```

## Comparison

| Feature | GitHub Actions | Cloud Build | Deploy Script |
|---------|---------------|-------------|---------------|
| **Automatic on push** | ✅ Yes | ✅ Yes | ❌ No (manual) |
| **Setup complexity** | Medium | Medium | Low |
| **GitHub integration** | ✅ Native | ✅ Available | ❌ No |
| **Best for** | Most users | GCP-only workflows | Quick local deployments |

## Troubleshooting

### GitHub Actions: Permission Errors

**Error:** `Permission denied` or `Access denied`

**Solution:**
```bash
# Verify service account has correct roles
gcloud projects get-iam-policy $PROJECT_ID \
  --flatten="bindings[].members" \
  --filter="bindings.members:serviceAccount:github-actions@$PROJECT_ID.iam.gserviceaccount.com"

# Re-grant permissions if needed
gcloud projects add-iam-policy-binding $PROJECT_ID \
  --member="serviceAccount:github-actions@$PROJECT_ID.iam.gserviceaccount.com" \
  --role="roles/run.admin"
```

### GitHub Actions: Secret Not Found

**Error:** `Secret 'GCP_SA_KEY' not found`

**Solution:**
1. Go to GitHub repository > Settings > Secrets
2. Verify secrets are set correctly
3. Check secret names match exactly (case-sensitive)

### GitHub Actions: Build Failures

**Error:** Build fails with authentication errors

**Solution:**
1. Verify `GCP_SA_KEY` contains valid JSON
2. Check service account key hasn't expired
3. Re-create service account key if needed

### Cloud Build: Trigger Not Firing

**Error:** Trigger doesn't fire on push

**Solution:**
```bash
# Check trigger exists
gcloud builds triggers list

# Test trigger manually
gcloud builds triggers run TRIGGER_NAME --branch=main
```

## Security Best Practices

1. **Never commit service account keys** - Always use GitHub Secrets or Secret Manager
2. **Rotate keys periodically** - Re-create service account keys every 90 days
3. **Use least privilege** - Only grant necessary IAM roles
4. **Monitor deployments** - Review GitHub Actions logs regularly

## Next Steps

After setting up automated deployment:

1. ✅ **Test deployment** - Push a small change to trigger deployment
2. ✅ **Monitor first deployment** - Check GitHub Actions logs
3. ✅ **Set up notifications** - Get notified of deployment status
4. ✅ **Review deployment history** - Track all deployments in GitHub Actions

## Resources

- [GitHub Actions Documentation](https://docs.github.com/en/actions)
- [Google Cloud Build Documentation](https://cloud.google.com/build/docs)
- [Cloud Run Deployment Guide](https://cloud.google.com/run/docs/deploying)
