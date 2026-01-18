#!/bin/bash
# Bootstrap GCP for GitHub Actions deployments to Cloud Run.
#
# What it does (from AUTOMATED_DEPLOYMENT.md Step 1, plus a bit of guardrails):
# - Enables required GCP APIs (Run, Cloud Build, Secret Manager)
# - Creates a "github-actions" service account (if missing)
# - Grants least-privilege-ish roles for the workflow
# - Creates a service account key JSON file (LOCAL ONLY) that you paste into GitHub Secrets
# - Optionally creates/updates Secret Manager secret "jwt-secret"
#
# IMPORTANT: Never commit the generated key file. It's in .gitignore, and the secret scan blocks it.

set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  scripts/setup_gcp_github_actions.sh --project <PROJECT_ID> [--region <REGION>] [--create-jwt-secret]

Options:
  --project <PROJECT_ID>        GCP project ID (required)
  --region <REGION>             Cloud Run region (default: us-central1)
  --create-jwt-secret           Create/update Secret Manager secret "jwt-secret" with a random value

Output:
  - Writes service account key to ./gcp-sa-key.json (LOCAL ONLY)
  - Prints instructions to copy it into GitHub Actions secret GCP_SA_KEY, then delete the file
EOF
}

PROJECT_ID=""
REGION="us-central1"
CREATE_JWT_SECRET="false"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --project)
      PROJECT_ID="${2:-}"; shift 2 ;;
    --region)
      REGION="${2:-}"; shift 2 ;;
    --create-jwt-secret)
      CREATE_JWT_SECRET="true"; shift 1 ;;
    -h|--help)
      usage; exit 0 ;;
    *)
      echo "Unknown argument: $1" >&2
      usage
      exit 2
      ;;
  esac
done

if [[ -z "$PROJECT_ID" ]]; then
  echo "Error: --project is required" >&2
  usage
  exit 2
fi

if ! command -v gcloud >/dev/null 2>&1; then
  echo "Error: gcloud is not installed or not on PATH" >&2
  exit 1
fi

echo "Setting gcloud project to: ${PROJECT_ID}"
gcloud config set project "${PROJECT_ID}" >/dev/null

echo "Enabling required services (run, cloudbuild, secretmanager)..."
gcloud services enable \
  run.googleapis.com \
  cloudbuild.googleapis.com \
  secretmanager.googleapis.com \
  --project "${PROJECT_ID}" >/dev/null

SA_NAME="github-actions"
SA_EMAIL="${SA_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"

if gcloud iam service-accounts describe "${SA_EMAIL}" --project "${PROJECT_ID}" >/dev/null 2>&1; then
  echo "Service account already exists: ${SA_EMAIL}"
else
  echo "Creating service account: ${SA_EMAIL}"
  gcloud iam service-accounts create "${SA_NAME}" \
    --display-name="GitHub Actions Deployment" \
    --project "${PROJECT_ID}" >/dev/null
fi

echo "Granting roles to ${SA_EMAIL} (project-level)..."
gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
  --member="serviceAccount:${SA_EMAIL}" \
  --role="roles/run.admin" >/dev/null

# Required for: `gcloud builds submit ...` in GitHub Actions
gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
  --member="serviceAccount:${SA_EMAIL}" \
  --role="roles/cloudbuild.builds.editor" >/dev/null

gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
  --member="serviceAccount:${SA_EMAIL}" \
  --role="roles/iam.serviceAccountUser" >/dev/null

gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
  --member="serviceAccount:${SA_EMAIL}" \
  --role="roles/storage.admin" >/dev/null

gcloud projects add-iam-policy-binding "${PROJECT_ID}" \
  --member="serviceAccount:${SA_EMAIL}" \
  --role="roles/secretmanager.secretAccessor" >/dev/null

KEY_FILE="gcp-sa-key.json"
echo "Creating service account key at ./${KEY_FILE}"
echo "WARNING: This file contains a private key. Do NOT commit it."
gcloud iam service-accounts keys create "${KEY_FILE}" \
  --iam-account="${SA_EMAIL}" \
  --project "${PROJECT_ID}" >/dev/null

if [[ "${CREATE_JWT_SECRET}" == "true" ]]; then
  if ! command -v openssl >/dev/null 2>&1; then
    echo "Error: openssl is required for --create-jwt-secret" >&2
    exit 1
  fi

  JWT_VALUE="$(openssl rand -hex 32)"

  if gcloud secrets describe jwt-secret --project "${PROJECT_ID}" >/dev/null 2>&1; then
    echo "Updating existing Secret Manager secret: jwt-secret"
  else
    echo "Creating Secret Manager secret: jwt-secret"
    gcloud secrets create jwt-secret --replication-policy="automatic" --project "${PROJECT_ID}" >/dev/null
  fi

  printf "%s" "${JWT_VALUE}" | gcloud secrets versions add jwt-secret --data-file=- --project "${PROJECT_ID}" >/dev/null

  echo "Ensuring Cloud Run default compute SA can access jwt-secret (common default)."
  PROJECT_NUMBER="$(gcloud projects describe "${PROJECT_ID}" --format="value(projectNumber)")"
  gcloud secrets add-iam-policy-binding jwt-secret \
    --member="serviceAccount:${PROJECT_NUMBER}-compute@developer.gserviceaccount.com" \
    --role="roles/secretmanager.secretAccessor" \
    --project "${PROJECT_ID}" >/dev/null || true
fi

cat <<EOF

Done.

Next steps (one-time):
  1) Copy the contents of ./${KEY_FILE} into GitHub repo secret: GCP_SA_KEY
  2) Set GitHub repo secret: GCP_PROJECT_ID=${PROJECT_ID}
  3) Set GitHub repo secret: GOOGLE_OAUTH_CLIENT_ID=<your client id>
  4) Delete the local key file:
       rm ./${KEY_FILE}

Cloud Run region configured in this script: ${REGION}
Workflow region is set in .github/workflows/deploy.yml (update if you use a different region).
EOF

