#!/bin/bash
# deploy_cloud_run.sh - Simple local deployment script for Cloud Run
#
# Mirrors the Cloud Run deploy command used in:
# - AUTOMATED_DEPLOYMENT.md (Option 3)
# - .github/workflows/deploy.yml
#
# Required env vars:
#   PROJECT_ID               (or pass --project)
#   GOOGLE_OAUTH_CLIENT_ID
#
# Optional env vars:
#   SERVICE_NAME (default: qzwhatnext)
#   REGION       (default: us-central1)
#   IMAGE_NAME   (default: gcr.io/$PROJECT_ID/$SERVICE_NAME)

set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  scripts/deploy_cloud_run.sh --project <PROJECT_ID> --google-oauth-client-id <CLIENT_ID> [--region <REGION>] [--service <NAME>]

Example:
  scripts/deploy_cloud_run.sh --project qzwhatnext --google-oauth-client-id "xxx.apps.googleusercontent.com"
EOF
}

PROJECT_ID="${PROJECT_ID:-}"
GOOGLE_OAUTH_CLIENT_ID="${GOOGLE_OAUTH_CLIENT_ID:-}"
SERVICE_NAME="${SERVICE_NAME:-qzwhatnext}"
REGION="${REGION:-us-central1}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --project)
      PROJECT_ID="${2:-}"; shift 2 ;;
    --google-oauth-client-id)
      GOOGLE_OAUTH_CLIENT_ID="${2:-}"; shift 2 ;;
    --service)
      SERVICE_NAME="${2:-}"; shift 2 ;;
    --region)
      REGION="${2:-}"; shift 2 ;;
    -h|--help)
      usage; exit 0 ;;
    *)
      echo "Unknown argument: $1" >&2
      usage
      exit 2
      ;;
  esac
done

if [[ -z "${PROJECT_ID}" ]]; then
  echo "Error: PROJECT_ID is required (env PROJECT_ID or --project)" >&2
  exit 2
fi

if [[ -z "${GOOGLE_OAUTH_CLIENT_ID}" ]]; then
  echo "Error: GOOGLE_OAUTH_CLIENT_ID is required (env GOOGLE_OAUTH_CLIENT_ID or --google-oauth-client-id)" >&2
  exit 2
fi

if ! command -v gcloud >/dev/null 2>&1; then
  echo "Error: gcloud is not installed or not on PATH" >&2
  exit 1
fi

IMAGE_NAME="${IMAGE_NAME:-gcr.io/${PROJECT_ID}/${SERVICE_NAME}}"

echo "Using project: ${PROJECT_ID}"
gcloud config set project "${PROJECT_ID}" >/dev/null

echo "Building and pushing image via Cloud Build: ${IMAGE_NAME}"
gcloud builds submit --tag "${IMAGE_NAME}"

echo "Deploying to Cloud Run service: ${SERVICE_NAME} (${REGION})"
gcloud run deploy "${SERVICE_NAME}" \
  --image "${IMAGE_NAME}" \
  --platform managed \
  --region "${REGION}" \
  --allow-unauthenticated \
  --set-env-vars "GOOGLE_OAUTH_CLIENT_ID=${GOOGLE_OAUTH_CLIENT_ID},DATABASE_URL=sqlite:///./qzwhatnext.db" \
  --set-secrets "JWT_SECRET_KEY=jwt-secret:latest" \
  --memory 512Mi \
  --timeout 300 \
  --quiet

echo "✅ Deployment complete. Service URL:"
gcloud run services describe "${SERVICE_NAME}" --region "${REGION}" --format="value(status.url)"

